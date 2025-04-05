import json
import time
from web3 import Web3
from eth_account import Account
from web3.exceptions import ContractLogicError

# Константы
SLIPPAGE = 30  # 3% slippage

FANTOM_RPC_URL = 'https://fantom-rpc.publicnode.com'
STARGATE_FANTOM_ADDRESS = Web3.to_checksum_address('0xAf5191B0De278C7286d6C7CC6ab6BB8A73bA2Cd6')
USDC_FANTOM_ADDRESS = Web3.to_checksum_address('0x28a92dde19D9989F39A49905d7C9C2FAc7799bDf')  # lzUSDC

# Chain IDs
FANTOM_LZ_CHAIN_ID = 112
ARBITRUM_LZ_CHAIN_ID = 110

# Pool IDs
SRC_POOL_ID = 21  # USDC (lzUSDC) на Fantom
DST_POOL_ID = 2   # USDT на Arbitrum

# Подключение
fantom_w3 = Web3(Web3.HTTPProvider(FANTOM_RPC_URL))
if not fantom_w3.is_connected():
    raise Exception('❌ Не удалось подключиться к Fantom RPC')

# ABIs
stargate_abi = json.load(open('bridge_abi.json'))
usdc_abi = json.load(open('erc20_abi.json'))

# Контракты
stargate_fantom_contract = fantom_w3.eth.contract(address=STARGATE_FANTOM_ADDRESS, abi=stargate_abi)
usdc_fantom_contract = fantom_w3.eth.contract(address=USDC_FANTOM_ADDRESS, abi=usdc_abi)

def swap_max_usdc_fantom_to_arbitrum(private_key):
    # Инициализация аккаунта
    ACCOUNT = Account.from_key(private_key)
    WALLET_ADDRESS = ACCOUNT.address

    # Функция проверки баланса
    def get_balance_usdc_fantom(address):
        balance = usdc_fantom_contract.functions.balanceOf(address).call()
        print(f"💰 Баланс lzUSDC на Fantom: {balance / 10**6:.2f} USDC")
        return balance

    # Функция проверки статуса транзакции с выводом ошибки
    def check_transaction_status(tx_hash):
        try:
            receipt = fantom_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if receipt['status'] == 1:
                print(f"✅ Транзакция выполнена: https://ftmscan.com/tx/{tx_hash.hex()}")
                return True
            else:
                print(f"❌ Транзакция провалилась: https://ftmscan.com/tx/{tx_hash.hex()}")
                print(f"Gas Used: {receipt['gasUsed']} из {receipt['gasLimit']}")
                tx = fantom_w3.eth.get_transaction(tx_hash)
                try:
                    fantom_w3.eth.call(tx, block_identifier=receipt['blockNumber'])
                except ContractLogicError as e:
                    print(f"Причина ошибки: {str(e)}")
                return False
        except Exception as e:
            print(f"❌ Ошибка при проверке транзакции: {str(e)}")
            return False

    # Функция свапа lzUSDC (Fantom) -> USDT (Arbitrum)
    def swap_usdc_fantom_to_arbitrum_usdt(account, amount):
        address = Web3.to_checksum_address(account.address)
        nonce = fantom_w3.eth.get_transaction_count(address)
        gas_price = fantom_w3.eth.gas_price

        # Комиссия LayerZero
        fees = stargate_fantom_contract.functions.quoteLayerZeroFee(
            ARBITRUM_LZ_CHAIN_ID,
            1,
            "0x0000000000000000000000000000000000000001",
            "0x",
            [0, 0, "0x0000000000000000000000000000000000000001"]
        ).call()
        fee = fees[0]
        print(f"💸 Комиссия Stargate (wei): {fee}")

        # Проверка FTM
        ftm_balance = fantom_w3.eth.get_balance(address)
        required_ftm = fee + (gas_price * 2000000)
        if ftm_balance < required_ftm:
            print(f"❌ Недостаточно FTM: нужно {required_ftm / 10**18:.6f} FTM, есть {ftm_balance / 10**18:.6f} FTM")
            return None

        # Approve
        allowance = usdc_fantom_contract.functions.allowance(address, STARGATE_FANTOM_ADDRESS).call()
        if allowance < amount:
            approve_txn = usdc_fantom_contract.functions.approve(STARGATE_FANTOM_ADDRESS, amount).build_transaction({
                'from': address,
                'gas': 150000,
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            signed_approve_txn = fantom_w3.eth.account.sign_transaction(approve_txn, account.key)
            approve_txn_hash = fantom_w3.eth.send_raw_transaction(signed_approve_txn.raw_transaction)
            print(f"FANTOM | lzUSDC APPROVED | https://ftmscan.com/tx/{approve_txn_hash.hex()}")
            if not check_transaction_status(approve_txn_hash):
                print("❌ Approve провалился, прерываем")
                return None
            nonce += 1
            time.sleep(10)

        # Stargate Swap
        chainId = ARBITRUM_LZ_CHAIN_ID
        source_pool_id = SRC_POOL_ID
        dest_pool_id = DST_POOL_ID
        refund_address = account.address
        amountIn = amount
        amountOutMin = amount - (amount * SLIPPAGE) // 1000
        lzTxObj = [0, 0, '0x0000000000000000000000000000000000000001']
        to = account.address
        data = '0x'

        swap_txn = stargate_fantom_contract.functions.swap(
            chainId, source_pool_id, dest_pool_id, refund_address, amountIn, amountOutMin, lzTxObj, to, data
        ).build_transaction({
            'from': address,
            'value': fee,
            'gas': 2000000,
            'gasPrice': fantom_w3.eth.gas_price,
            'nonce': fantom_w3.eth.get_transaction_count(address),
        })

        signed_swap_txn = fantom_w3.eth.account.sign_transaction(swap_txn, account.key)
        swap_txn_hash = fantom_w3.eth.send_raw_transaction(signed_swap_txn.raw_transaction)
        print(f"🚀 Свап отправлен: https://ftmscan.com/tx/{swap_txn_hash.hex()}")
        print(f"Статус: https://layerzeroscan.com/tx/{swap_txn_hash.hex()}")
        return swap_txn_hash

    # Основной процесс
    print(f"\n▶️ Адрес кошелька: {WALLET_ADDRESS}")
    balance = get_balance_usdc_fantom(WALLET_ADDRESS)
    if balance == 0:
        print("❌ Баланс lzUSDC равен нулю")
        return None

    amount_usdc = balance  # Отправляем максимальный баланс
    print(f"Будет отправлено максимальное количество: {amount_usdc / 10**6:.2f} lzUSDC")
    print("Начинаем свап lzUSDC (Fantom) -> USDT (Arbitrum)...")
    tx_hash = swap_usdc_fantom_to_arbitrum_usdt(ACCOUNT, amount_usdc)
    if tx_hash:
        print("Ожидаем завершения...")
        time.sleep(20)
        check_transaction_status(tx_hash)
        return tx_hash
    return None

# Пример вызова
if __name__ == "__main__":
    PRIVATE_KEY = ''
    tx_hash = swap_max_usdc_fantom_to_arbitrum(PRIVATE_KEY)
    if tx_hash:
        print(f"Транзакция успешно выполнена: {tx_hash.hex()}")