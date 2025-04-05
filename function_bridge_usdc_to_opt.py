import json
from web3 import Web3
from eth_account import Account

def swap_usdc_fantom_to_optimism(private_key):
    # Конфигурация
    FANTOM_RPC = 'https://fantom-rpc.publicnode.com'
    USDC_ADDRESS = Web3.to_checksum_address('0x28a92dde19D9989F39A49905d7C9C2FAc7799bDf')  # USDC на Fantom
    STARGATE_ROUTER = Web3.to_checksum_address('0x45A01E4e04F14f7A4a6702c74187c5F6222033cd')  # Stargate Router на Fantom
    FANTOM_CHAIN_ID = 112  # Stargate ID для Fantom
    OPTIMISM_CHAIN_ID = 111  # Stargate ID для Optimism

    # Инициализация аккаунта
    account = Account.from_key(private_key)
    WALLET_ADDRESS = account.address
    print(f'Адрес кошелька: {WALLET_ADDRESS}')

    # Подключение к Fantom
    web3 = Web3(Web3.HTTPProvider(FANTOM_RPC))
    if not web3.is_connected():
        print('❌ Не удалось подключиться к Fantom RPC')
        return None
    print('✅ Успешно подключено к Fantom RPC')

    # Проверка баланса FTM
    ftm_balance = web3.eth.get_balance(WALLET_ADDRESS)
    ftm_balance_in_ether = web3.from_wei(ftm_balance, 'ether')
    print(f'Баланс FTM: {ftm_balance_in_ether} FTM')
    if ftm_balance_in_ether < 0.5:
        print(f'❌ Недостаточно FTM! Требуется минимум 0.5 FTM')
        return None

    # ABI для ERC20 и Stargate
    ERC20_ABI = json.loads('''[{"constant":false,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},{"constant":true,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}]''')
    STARGATE_ABI = json.loads('''[{"inputs":[{"internalType":"uint16","name":"_dstChainId","type":"uint16"},{"internalType":"uint256","name":"_srcPoolId","type":"uint256"},{"internalType":"uint256","name":"_dstPoolId","type":"uint256"},{"internalType":"address payable","name":"_refundAddress","type":"address"},{"internalType":"uint256","name":"_amountLD","type":"uint256"},{"internalType":"uint256","name":"_minAmountLD","type":"uint256"},{"internalType":"bytes","name":"_lzTxParams","type":"bytes"},{"internalType":"address","name":"_to","type":"address"},{"internalType":"bytes","name":"_payload","type":"bytes"}],"name":"swap","stateMutability":"payable","type":"function"}]''')

    # Инициализация контрактов
    usdc_contract = web3.eth.contract(address=USDC_ADDRESS, abi=ERC20_ABI)
    stargate_contract = web3.eth.contract(address=STARGATE_ROUTER, abi=STARGATE_ABI)

    # Проверка баланса USDC и использование максимального количества
    balance = usdc_contract.functions.balanceOf(WALLET_ADDRESS).call()
    balance_in_usdc = balance / 10**6
    print(f'Баланс USDC: {balance_in_usdc} USDC')
    if balance == 0:
        print(f'❌ Баланс USDC равен нулю!')
        return None

    amount_usdc = balance  # Используем весь доступный баланс
    print(f'Будет отправлено максимальное количество: {amount_usdc / 10**6} USDC')

    # Определяем gas_price
    gas_price = web3.eth.gas_price
    print(f'Текущая цена газа: {gas_price} wei')

    # Approve USDC для Stargate
    allowance = usdc_contract.functions.allowance(WALLET_ADDRESS, STARGATE_ROUTER).call()
    print(f'Allowance для Stargate: {allowance / 10**6} USDC')
    if allowance < amount_usdc:
        nonce = web3.eth.get_transaction_count(WALLET_ADDRESS, 'pending')
        approve_tx = usdc_contract.functions.approve(STARGATE_ROUTER, amount_usdc).build_transaction({
            'from': WALLET_ADDRESS,
            'gas': 50000,
            'gasPrice': gas_price * 2,
            'nonce': nonce
        })
        signed_approve_tx = account.sign_transaction(approve_tx)
        approve_tx_hash = web3.eth.send_raw_transaction(signed_approve_tx.raw_transaction)
        print(f'Транзакция approve отправлена: {approve_tx_hash.hex()}')
        receipt = web3.eth.wait_for_transaction_receipt(approve_tx_hash, timeout=120)
        if receipt['status'] == 0:
            print(f'❌ Approve провалился! Логи: {receipt}')
            return None
        print('✅ Approve выполнен!')
    else:
        print('Allowance уже достаточный, пропускаем approve.')

    # Параметры для swap
    dst_chain_id = OPTIMISM_CHAIN_ID  # 111 для Optimism
    src_pool_id = 1   # USDC на Fantom (по Payload)
    dst_pool_id = 21  # USDC.e на Optimism (по документации, хотя Payload показал 21)
    refund_address = WALLET_ADDRESS
    amount_ld = amount_usdc  # Максимальный баланс
    min_amount_ld = int(amount_usdc * 0.99)  # 1% slippage
    lz_tx_params = bytes.fromhex('0001000000000000000000000000000000000000000000000000000000000007a120')  # gasLimit=500,000
    to_address = WALLET_ADDRESS
    payload = bytes.fromhex('')

    swap_tx = stargate_contract.functions.swap(
        dst_chain_id,
        src_pool_id,
        dst_pool_id,
        refund_address,
        amount_ld,
        min_amount_ld,
        lz_tx_params,
        to_address,
        payload
    ).build_transaction({
        'from': WALLET_ADDRESS,
        'value': 500000000000000000,  # 0.5 FTM
        'gas': 600000,
        'gasPrice': gas_price * 2,
        'nonce': web3.eth.get_transaction_count(WALLET_ADDRESS, 'pending')
    })

    # Оценка газа
    try:
        estimated_gas = web3.eth.estimate_gas(swap_tx)
        swap_tx['gas'] = int(estimated_gas * 1.2)
        print(f'Оценка газа: {estimated_gas} единиц')
    except Exception as e:
        print(f'Ошибка оценки газа: {str(e)}')
        print('Используем запасной газ: 600,000')

    # Отправка транзакции
    signed_swap_tx = account.sign_transaction(swap_tx)
    swap_tx_hash = web3.eth.send_raw_transaction(signed_swap_tx.raw_transaction)
    print(f'Транзакция отправлена: {swap_tx_hash.hex()}')
    print(f'Проверяй на FTMScan: https://ftmscan.com/tx/{swap_tx_hash.hex()}')

    receipt = web3.eth.wait_for_transaction_receipt(swap_tx_hash, timeout=120)
    if receipt['status'] == 0:
        print(f'❌ Транзакция провалилась! Логи: {receipt}')
        return None
    else:
        print('✅ Успех! Проверяй USDC.e на Optimism: https://optimistic.etherscan.io/address/' + WALLET_ADDRESS)
        return swap_tx_hash

# Пример вызова
if __name__ == "__main__":
    PRIVATE_KEY = ''
    tx_hash = swap_usdc_fantom_to_optimism(PRIVATE_KEY)
    if tx_hash:
        print(f'Транзакция успешно выполнена: {tx_hash.hex()}')