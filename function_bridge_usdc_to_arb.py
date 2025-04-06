import json
import time
from web3 import Web3
from eth_account import Account
from web3.exceptions import ContractLogicError

# Константы
SLIPPAGE = 30
FANTOM_RPC_URL = 'https://fantom-rpc.publicnode.com'
STARGATE_FANTOM_ADDRESS = Web3.to_checksum_address('0xAf5191B0De278C7286d6C7CC6ab6BB8A73bA2Cd6')
USDC_FANTOM_ADDRESS = Web3.to_checksum_address('0x28a92dde19D9989F39A49905d7C9C2FAc7799bDf')

FANTOM_LZ_CHAIN_ID = 112
ARBITRUM_LZ_CHAIN_ID = 110
SRC_POOL_ID = 21
DST_POOL_ID = 2

fantom_w3 = Web3(Web3.HTTPProvider(FANTOM_RPC_URL))
if not fantom_w3.is_connected():
    raise Exception('❌ Не удалось подключиться к Fantom RPC')

stargate_abi = json.load(open('bridge_abi.json'))
usdc_abi = json.load(open('erc20_abi.json'))

stargate_fantom_contract = fantom_w3.eth.contract(address=STARGATE_FANTOM_ADDRESS, abi=stargate_abi)
usdc_fantom_contract = fantom_w3.eth.contract(address=USDC_FANTOM_ADDRESS, abi=usdc_abi)


def get_balance_usdc_fantom(address):
    balance = usdc_fantom_contract.functions.balanceOf(address).call()
    print(f"💰 Баланс lzUSDC на Fantom: {balance / 10**6:.2f} USDC")
    return balance


def check_transaction_status(tx_hash):
    try:
        receipt = fantom_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt and receipt.get('status') == 1:
            print(f"✅ Транзакция выполнена: https://ftmscan.com/tx/{tx_hash.hex()}")
            return True
        else:
            print(f"❌ Транзакция провалилась: https://ftmscan.com/tx/{tx_hash.hex()}")
            if receipt:
                print(f"Gas Used: {receipt.get('gasUsed', 'N/A')}")
                tx = fantom_w3.eth.get_transaction(tx_hash)
                try:
                    fantom_w3.eth.call(tx, block_identifier=receipt.get('blockNumber'))
                except ContractLogicError as e:
                    print(f"Причина ошибки: {str(e)}")
            return False
    except Exception as e:
        print(f"❌ Ошибка при проверке транзакции: {str(e)}")
        return False


def swap_usdc_fantom_to_arbitrum_usdt(account, amount):
    address = Web3.to_checksum_address(account.address)
    nonce = fantom_w3.eth.get_transaction_count(address)
    gas_price = fantom_w3.eth.gas_price

    # Проверка FTM баланса
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
        print("❌ Баланс FTM равен 0 после всех попыток. Пополните кошелек.")
        return None

    # Stargate fee
    fees = stargate_fantom_contract.functions.quoteLayerZeroFee(
        ARBITRUM_LZ_CHAIN_ID, 1, "0x0000000000000000000000000000000000000001", "0x",
        [0, 0, "0x0000000000000000000000000000000000000001"]
    ).call()
    fee = fees[0]
    print(f"💸 Комиссия Stargate (wei): {fee}")

    # Approve если нужно
    approve_gas = 0
    allowance = usdc_fantom_contract.functions.allowance(address, STARGATE_FANTOM_ADDRESS).call()
    print(f"🔐 Текущее разрешение: {allowance / 10**6:.2f} lzUSDC")
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
            print(f"❌ Недостаточно FTM для approve")
            return None

        signed_approve_txn = fantom_w3.eth.account.sign_transaction(approve_txn, account.key)
        try:
            approve_txn_hash = fantom_w3.eth.send_raw_transaction(signed_approve_txn.raw_transaction)
            print(f"✅ APPROVE: https://ftmscan.com/tx/{approve_txn_hash.hex()}")
            if not check_transaction_status(approve_txn_hash):
                print("❌ Approve провалился")
                return None
        except Exception as e:
            print(f"❌ Ошибка при отправке approve: {str(e)}")
            return None
        nonce += 1
        time.sleep(10)

    # Swap
    balance_before_swap = usdc_fantom_contract.functions.balanceOf(address).call()
    if balance_before_swap < amount:
        print(f"❌ Недостаточно lzUSDC для свапа: нужно {amount / 10**6:.2f}, есть {balance_before_swap / 10**6:.2f}")
        return None

    swap_txn = stargate_fantom_contract.functions.swap(
        ARBITRUM_LZ_CHAIN_ID, SRC_POOL_ID, DST_POOL_ID, address, amount,
        amount - (amount * SLIPPAGE) // 1000,
        [0, 0, '0x0000000000000000000000000000000000000001'],
        address, '0x'
    ).build_transaction({
        'from': address,
        'value': fee,
        'gasPrice': gas_price,
        'nonce': nonce,
    })

    try:
        swap_gas = int(fantom_w3.eth.estimate_gas(swap_txn) * 1.2)
        swap_txn['gas'] = swap_gas
        print(f"⛽️ Газ на свап: {swap_gas}")
    except Exception as e:
        print(f"❌ Ошибка при оценке газа на свап: {str(e)}")
        return None

    required_ftm = fee + gas_price * (approve_gas + swap_gas)
    ftm_balance = fantom_w3.eth.get_balance(address)
    if ftm_balance < required_ftm:
        print(f"❌ Недостаточно FTM для выполнения транзакции")
        return None

    signed_swap_txn = fantom_w3.eth.account.sign_transaction(swap_txn, account.key)
    try:
        swap_txn_hash = fantom_w3.eth.send_raw_transaction(signed_swap_txn.raw_transaction)
        print(f"🚀 Свап отправлен: https://ftmscan.com/tx/{swap_txn_hash.hex()}")
        print(f"Статус LayerZero: https://layerzeroscan.com/tx/{swap_txn_hash.hex()}")
        return swap_txn_hash
    except Exception as e:
        print(f"❌ Ошибка при отправке свапа: {str(e)}")
        return None


def swap_max_usdc_fantom_to_arbitrum(private_key):
    account = Account.from_key(private_key)
    wallet_address = account.address

    print(f"\n▶️ Кошелек: {wallet_address}")
    balance = get_balance_usdc_fantom(wallet_address)

    if balance == 0:
        print("❌ Баланс lzUSDC равен нулю, прекращаем выполнение.")
        return None

    print(f"📤 Отправка максимального количества: {balance / 10**6:.2f} lzUSDC")
    print("🔁 Начинаем свап lzUSDC (Fantom) -> USDT (Arbitrum)...")

    tx_hash = swap_usdc_fantom_to_arbitrum_usdt(account, balance)
    if tx_hash:
        print("⏳ Ожидаем завершения транзакции...")
        time.sleep(20)
        check_transaction_status(tx_hash)
        return tx_hash
    return None


if __name__ == "__main__":
    PRIVATE_KEY = ''  # Вставь свой приватный ключ
    tx_hash = swap_max_usdc_fantom_to_arbitrum(PRIVATE_KEY)
    if tx_hash:
        print(f"🎉 Успешная транзакция: {tx_hash.hex()}")
