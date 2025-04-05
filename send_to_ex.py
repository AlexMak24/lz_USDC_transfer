import json
from web3 import Web3
from eth_account import Account

# Константы для сетей
ARBITRUM_RPC = 'https://arb1.arbitrum.io/rpc'
OPTIMISM_RPC = 'https://mainnet.optimism.io'

# Адреса токенов
USDC_ARBITRUM_ADDRESS = Web3.to_checksum_address('0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9')  # USDT на Arbitrum
USDT_OPTIMISM_ADDRESS = Web3.to_checksum_address('0x7F5c764cBc14f9669B88837ca1490cCa17c31607')  # USDC на Optimism

# ABI для ERC20 (метод transfer)
ERC20_ABI = json.loads('''[
    {"constant": false, "inputs": [{"name": "_to", "type": "address"},{"name": "_value", "type": "uint256"}],"name": "transfer","outputs": [{"name": "","type": "bool"}],"type": "function"},
    {"constant": true, "inputs": [{"name": "_owner", "type": "address"}],"name": "balanceOf","outputs": [{"name": "balance","type": "uint256"}],"type": "function"}
]''')


def send_to_exchange_wallet(private_key, network, destination_address):
    """
    Отправляет максимальное количество токенов на указанный адрес в выбранной сети.

    :param private_key: Приватный ключ кошелька
    :param network: Сеть ('arb' для Arbitrum или 'opt' для Optimism)
    :param destination_address: Адрес, на который отправляем токены
    :return: Хэш транзакции или None при ошибке
    """
    # Проверка валидности адреса назначения
    try:
        destination_address = Web3.to_checksum_address(destination_address)
    except ValueError:
        print(f'❌ Неверный формат адреса назначения: {destination_address}')
        return None

    # Инициализация аккаунта
    account = Account.from_key(private_key)
    wallet_address = account.address
    print(f'Адрес кошелька: {wallet_address}')

    # Выбор сети и токена
    if network.lower() == 'arb':
        rpc_url = ARBITRUM_RPC
        token_address = USDC_ARBITRUM_ADDRESS
        token_name = 'USDC'
        explorer_url = 'https://arbiscan.io'
    elif network.lower() == 'opt':
        rpc_url = OPTIMISM_RPC
        token_address = USDT_OPTIMISM_ADDRESS
        token_name = 'USDT'
        explorer_url = 'https://optimistic.etherscan.io'
    else:
        print(f'❌ Неверная сеть: {network}. Используйте "arb" или "opt"')
        return None

    # Подключение к сети
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        print(f'❌ Не удалось подключиться к {network} RPC')
        return None
    print(f'✅ Успешно подключено к {network} RPC')

    # Проверка баланса нативной валюты (ETH)
    eth_balance = web3.eth.get_balance(wallet_address)
    eth_balance_in_ether = web3.from_wei(eth_balance, 'ether')
    print(f'Баланс ETH: {eth_balance_in_ether} ETH')
    if eth_balance_in_ether < 0.001:  # Минимальный запас для газа
        print(f'❌ Недостаточно ETH! Требуется минимум 0.001 ETH')
        return None

    # Инициализация контракта токена
    token_contract = web3.eth.contract(address=token_address, abi=ERC20_ABI)

    # Проверка баланса токена и использование максимального количества
    balance = token_contract.functions.balanceOf(wallet_address).call()
    balance_in_tokens = balance / 10 ** 6  # USDC и USDT имеют 6 decimals
    print(f'Баланс {token_name}: {balance_in_tokens} {token_name}')
    if balance == 0:
        print(f'❌ Баланс {token_name} равен нулю!')
        return None

    amount_to_send = balance  # Отправляем максимальный баланс
    print(
        f'Будет отправлено максимальное количество: {amount_to_send / 10 ** 6} {token_name} на адрес: {destination_address}')

    # Определяем gas_price
    gas_price = web3.eth.gas_price
    print(f'Текущая цена газа: {gas_price} wei')

    # Формируем транзакцию transfer
    nonce = web3.eth.get_transaction_count(wallet_address, 'pending')
    transfer_tx = token_contract.functions.transfer(destination_address, amount_to_send).build_transaction({
        'from': wallet_address,
        'gas': 100000,  # Оценочный лимит газа для transfer
        'gasPrice': gas_price * 2,
        'nonce': nonce
    })

    # Оценка газа
    try:
        estimated_gas = web3.eth.estimate_gas(transfer_tx)
        transfer_tx['gas'] = int(estimated_gas * 1.2)
        print(f'Оценка газа: {estimated_gas} единиц')
    except Exception as e:
        print(f'Ошибка оценки газа: {str(e)}')
        print('Используем запасной газ: 100,000')

    # Отправка транзакции
    signed_transfer_tx = account.sign_transaction(transfer_tx)
    transfer_tx_hash = web3.eth.send_raw_transaction(signed_transfer_tx.raw_transaction)
    print(f'Транзакция отправлена: {transfer_tx_hash.hex()}')
    print(f'Проверяй на {network} Explorer: {explorer_url}/tx/{transfer_tx_hash.hex()}')

    receipt = web3.eth.wait_for_transaction_receipt(transfer_tx_hash, timeout=120)
    if receipt['status'] == 0:
        print(f'❌ Транзакция провалилась! Логи: {receipt}')
        return None
    else:
        print(f'✅ Успех! Токены отправлены на адрес: {destination_address}')
        return transfer_tx_hash


# Пример вызова
if __name__ == "__main__":
    PRIVATE_KEY = ''
    DESTINATION_ADDRESS = ''  # Укажите реальный адрес

    # Отправка USDC на Arbitrum
    tx_hash_arb = send_to_exchange_wallet(PRIVATE_KEY, 'arb', DESTINATION_ADDRESS)
    if tx_hash_arb:
        print(f'Транзакция на Arbitrum успешно выполнена: {tx_hash_arb.hex()}')

    # Отправка USDT на Optimism
    #tx_hash_opt = send_to_exchange_wallet(PRIVATE_KEY, 'opt', DESTINATION_ADDRESS)
    #if tx_hash_opt:
    #    print(f'Транзакция на Optimism успешно выполнена: {tx_hash_opt.hex()}')