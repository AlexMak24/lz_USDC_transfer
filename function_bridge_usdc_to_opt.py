import json
import time
from web3 import Web3
from eth_account import Account
from web3.exceptions import ContractLogicError

# Константы
SLIPPAGE = 30  # Оставляем как в исходном коде (3%)
FANTOM_RPC_URL = 'https://fantom-rpc.publicnode.com'
STARGATE_FANTOM_ADDRESS = Web3.to_checksum_address('0x45A01E4e04F14f7A4a6702c74187c5F6222033cd')  # Stargate Router на Fantom
USDC_FANTOM_ADDRESS = Web3.to_checksum_address('0x28a92dde19D9989F39A49905d7C9C2FAc7799bDf')  # lzUSDC на Fantom

FANTOM_LZ_CHAIN_ID = 112  # Stargate ID для Fantom
OPTIMISM_LZ_CHAIN_ID = 111  # Stargate ID для Optimism
SRC_POOL_ID = 1  # USDC на Fantom (как в вашем пробном коде)
DST_POOL_ID = 21  # USDC.e на Optimism (как в вашем пробном коде)

fantom_w3 = Web3(Web3.HTTPProvider(FANTOM_RPC_URL))
if not fantom_w3.is_connected():
    raise Exception('❌ Не удалось подключиться к Fantom RPC')

# ABI для Stargate и ERC20 (предполагается, что они у вас есть в файлах)
stargate_abi = json.load(open('bridge_abi.json'))  # Убедитесь, что файл существует
usdc_abi = json.load(open('erc20_abi.json'))  # Убедитесь, что файл существует

stargate_fantom_contract = fantom_w3.eth.contract(address=STARGATE_FANTOM_ADDRESS, abi=stargate_abi)
usdc_fantom_contract = fantom_w3.eth.contract(address=USDC_FANTOM_ADDRESS, abi=usdc_abi)

def swap_max_usdc_fantom_to_optimism(private_key):
    ACCOUNT = Account.from_key(private_key)
    WALLET_ADDRESS = ACCOUNT.address

    def get_balance_usdc_fantom(address):
        balance = usdc_fantom_contract.functions.balanceOf(address).call()
        print(f"💰 Баланс lzUSDC на Fantom: {balance / 10**6:.2f} USDC")
        return balance

    def check_transaction_status(tx_hash):
        try:
            receipt = fantom_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)  # Увеличенный таймаут
            if receipt and receipt.get('status') == 1:
                print(f"✅ Транзакция выполнена: https://ftmscan.com/tx/{tx_hash.hex()}")
                return True
            else:
                print(f"❌ Транзакция провалилась: https://ftmscan.com/tx/{tx_hash.hex()}")
                if receipt:
                    print(f"Gas Used: {receipt.get('gasUsed', 'N/A')} из {receipt.get('gasLimit', 'N/A')}")
                    tx = fantom_w3.eth.get_transaction(tx_hash)
                    try:
                        fantom_w3.eth.call(tx, block_identifier=receipt.get('blockNumber'))
                    except ContractLogicError as e:
                        print(f"Причина ошибки: {str(e)}")
                return False
        except Exception as e:
            print(f"❌ Ошибка при проверке транзакции: {str(e)}")
            return False

    def swap_usdc_fantom_to_optimism_usdc(account, amount):
        address = Web3.to_checksum_address(account.address)
        nonce = fantom_w3.eth.get_transaction_count(address)
        gas_price = fantom_w3.eth.gas_price

        # Проверка баланса FTM с ожиданием
        max_attempts = 10
        for attempt in range(max_attempts):
            ftm_balance = fantom_w3.eth.get_balance(address)
            print(f"💰 Баланс FTM (попытка {attempt + 1}/{max_attempts}): {ftm_balance / 10**18:.6f} FTM")
            if ftm_balance > 0:
                break
            if attempt < max_attempts - 1:
                print("Ожидаем зачисления FTM... (10 секунд)")
                time.sleep(10)
        if ftm_balance == 0:
            print("❌ Баланс FTM равен 0 после всех попыток. Пополните кошелек для оплаты газа и комиссии Stargate.")
            return None

        # Оценка комиссии LayerZero
        fees = stargate_fantom_contract.functions.quoteLayerZeroFee(
            OPTIMISM_LZ_CHAIN_ID,
            1,  # functionType для swap
            "0x0000000000000000000000000000000000000001",  # Placeholder как в исходнике
            "0x",  # Пустой payload
            [0, 0, "0x0000000000000000000000000000000000000001"]  # Параметры LayerZero
        ).call()
        fee = fees[0]
        print(f"💸 Комиссия Stargate (wei): {fee} ({fee / 10**18:.6f} FTM)")

        # Проверка и выполнение approve
        approve_gas = 0
        allowance = usdc_fantom_contract.functions.allowance(address, STARGATE_FANTOM_ADDRESS).call()
        print(f"Текущее разрешение: {allowance / 10**6:.2f} lzUSDC")
        if allowance < amount:
            approve_txn = usdc_fantom_contract.functions.approve(STARGATE_FANTOM_ADDRESS, amount).build_transaction({
                'from': address,
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            try:
                approve_gas = int(fantom_w3.eth.estimate_gas(approve_txn) * 1.2)
                approve_txn['gas'] = approve_gas
            except Exception as e:
                print(f"❌ Ошибка при оценке газа для approve: {str(e)}")
                return None

            required_ftm_for_approve = gas_price * approve_gas
            if ftm_balance < required_ftm_for_approve:
                print(f"❌ Недостаточно FTM для approve: нужно {required_ftm_for_approve / 10**18:.6f} FTM, есть {ftm_balance / 10**18:.6f} FTM")
                return None

            signed_approve_txn = fantom_w3.eth.account.sign_transaction(approve_txn, account.key)
            try:
                approve_txn_hash = fantom_w3.eth.send_raw_transaction(signed_approve_txn.raw_transaction)
                print(f"FANTOM | lzUSDC APPROVED | https://ftmscan.com/tx/{approve_txn_hash.hex()}")
                if not check_transaction_status(approve_txn_hash):
                    print("❌ Approve провалился, прерываем")
                    return None
            except Exception as e:
                print(f"❌ Ошибка при отправке approve: {str(e)}")
                return None
            nonce += 1
            time.sleep(10)

        # Проверка баланса перед swap
        balance_before_swap = usdc_fantom_contract.functions.balanceOf(address).call()
        if balance_before_swap < amount:
            print(f"❌ Недостаточно lzUSDC: нужно {amount / 10**6:.2f}, есть {balance_before_swap / 10**6:.2f}")
            return None

        # Подготовка транзакции swap
        swap_txn = stargate_fantom_contract.functions.swap(
            OPTIMISM_LZ_CHAIN_ID,
            SRC_POOL_ID,
            DST_POOL_ID,
            address,  # refundAddress
            amount,
            amount - (amount * SLIPPAGE) // 1000,  # minAmount с учетом slippage
            [0, 0, '0x0000000000000000000000000000000000000001'],  # lzTxParams
            address,  # toAddress
            '0x'  # payload
        ).build_transaction({
            'from': address,
            'value': fee,
            'gasPrice': gas_price,
            'nonce': nonce,
        })
        try:
            swap_gas = int(fantom_w3.eth.estimate_gas(swap_txn) * 1.2)
            swap_txn['gas'] = swap_gas
            print(f"Оценка газа для свапа: {swap_txn['gas']}")
        except Exception as e:
            print(f"❌ Ошибка при оценке газа для свапа: {str(e)}")
            swap_txn['gas'] = 1000000  # Запасной газ
            print("Используем запасной газ: 1,000,000")

        # Проверка достаточности FTM
        ftm_balance = fantom_w3.eth.get_balance(address)  # Обновляем баланс после approve
        required_ftm = fee + gas_price * (approve_gas + swap_gas if approve_gas else swap_gas)
        if ftm_balance < required_ftm:
            print(f"❌ Недостаточно FTM: нужно {required_ftm / 10**18:.6f} FTM, есть {ftm_balance / 10**18:.6f} FTM")
            return None

        # Отправка транзакции swap
        signed_swap_txn = fantom_w3.eth.account.sign_transaction(swap_txn, account.key)
        try:
            swap_txn_hash = fantom_w3.eth.send_raw_transaction(signed_swap_txn.raw_transaction)
            print(f"🚀 Свап отправлен: https://ftmscan.com/tx/{swap_txn_hash.hex()}")
            print(f"Статус: https://layerzeroscan.com/tx/{swap_txn_hash.hex()}")
            return swap_txn_hash
        except Exception as e:
            print(f"❌ Ошибка при отправке свапа: {str(e)}")
            return None

    print(f"\n▶️ Адрес кошелька: {WALLET_ADDRESS}")
    balance = get_balance_usdc_fantom(WALLET_ADDRESS)
    if balance == 0:
        print("❌ Баланс lzUSDC равен нулю")
        return None

    amount_usdc = balance
    print(f"Будет отправлено максимальное количество: {amount_usdc / 10**6:.2f} lzUSDC")
    print("Начинаем свап lzUSDC (Fantom) -> USDC.e (Optimism)...")
    tx_hash = swap_usdc_fantom_to_optimism_usdc(ACCOUNT, amount_usdc)
    if tx_hash:
        print("Ожидаем завершения...")
        time.sleep(20)
        check_transaction_status(tx_hash)
        return tx_hash
    return None

if __name__ == "__main__":
    PRIVATE_KEY = ''  # Замените на ваш приватный ключ
    tx_hash = swap_max_usdc_fantom_to_optimism(PRIVATE_KEY)
    if tx_hash:
        print(f"Транзакция успешно выполнена: {tx_hash.hex()}")