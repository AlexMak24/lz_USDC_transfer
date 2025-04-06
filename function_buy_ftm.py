import json
import requests
from web3 import Web3
from eth_account import Account
from web3.exceptions import ContractLogicError

# Конфигурация глобальных констант
BASE_RPC = 'https://mainnet.base.org'
USDC_ADDRESS = Web3.to_checksum_address('0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')  # USDC на Base
LIFI_CONTRACT_ADDRESS = Web3.to_checksum_address('0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE')
BASE_CHAIN_ID = 8453  # Base
FANTOM_CHAIN_ID = 250  # Fantom
FTM_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"  # FTM на Fantom

# ABI для ERC20
ERC20_ABI = json.loads('''
[
    {"constant": false, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],"name": "approve", "outputs": [{"name": "", "type": "bool"}],"type": "function"},
    {"constant": true, "inputs": [{"name": "_owner", "type": "address"}],"name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}],"type": "function"},
    {"constant": true, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],"name": "allowance", "outputs": [{"name": "", "type": "uint256"}],"type": "function"}
]
''')

# Функция для перевода USDC с Base на FTM
def swap_usdc_base_to_fantom(private_key, amount_usdc, rpc_url=BASE_RPC, from_token=USDC_ADDRESS, to_chain_id=FANTOM_CHAIN_ID, to_token=FTM_TOKEN_ADDRESS, bridge="squid"):
    """
    Переводит USDC с Base на Fantom через LI.FI.

    :param private_key: Приватный ключ кошелька
    :param amount_usdc: Количество USDC для перевода (в wei, например, 4000000 для 4 USDC)
    :param rpc_url: URL RPC для Base (по умолчанию 'https://mainnet.base.org')
    :param from_token: Адрес токена на Base (по умолчанию USDC)
    :param to_chain_id: Chain ID сети назначения (по умолчанию 250 для Fantom)
    :param to_token: Адрес токена на сети назначения (по умолчанию FTM)
    :param bridge: Используемый мост (по умолчанию "squid")
    :return: Хэш транзакции или None в случае ошибки
    """
    # Инициализация аккаунта
    account = Account.from_key(private_key)
    wallet_address = account.address
    print(f"\n▶️ Адрес кошелька: {wallet_address}")

    # Подключение к Base
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        print(f'❌ Не удалось подключиться к Base RPC: {rpc_url}')
        return None
    print('✅ Успешно подключено к Base RPC')

    # Инициализация контракта USDC
    usdc_contract = web3.eth.contract(address=from_token, abi=ERC20_ABI)

    # Проверка баланса ETH
    eth_balance = web3.eth.get_balance(wallet_address)
    eth_balance_in_ether = web3.from_wei(eth_balance, 'ether')
    print(f'Баланс ETH на адресе {wallet_address}: {eth_balance_in_ether} ETH')
    if eth_balance_in_ether < 0.001:
        print(f'❌ Недостаточно ETH! Требуется минимум 0.001 ETH, доступно: {eth_balance_in_ether}')
        return None

    # Проверка баланса USDC
    balance = usdc_contract.functions.balanceOf(wallet_address).call()
    balance_in_usdc = balance / 10**6
    print(f'Баланс USDC на адресе {wallet_address}: {balance_in_usdc} USDC')
    if balance < amount_usdc:
        print(f'❌ Недостаточно USDC! Требуется: {amount_usdc / 10**6}, доступно: {balance_in_usdc}')
        return None

    # Шаг 1: Проверка и выполнение approve
    allowance = usdc_contract.functions.allowance(wallet_address, LIFI_CONTRACT_ADDRESS).call()
    print(f'Текущий allowance для LI.FI: {allowance / 10**6} USDC')
    if allowance < amount_usdc:
        nonce = web3.eth.get_transaction_count(wallet_address, 'pending')
        gas_price = web3.eth.gas_price * 2

        approve_tx = usdc_contract.functions.approve(LIFI_CONTRACT_ADDRESS, amount_usdc).build_transaction({
            'from': wallet_address,
            'gasPrice': gas_price,
            'nonce': nonce,
            'chainId': BASE_CHAIN_ID
        })

        try:
            estimated_gas = web3.eth.estimate_gas(approve_tx)
            approve_tx['gas'] = int(estimated_gas * 1.2)
            print(f'Оценка газа для approve: {estimated_gas} единиц')
        except Exception as e:
            print(f'Ошибка оценки газа для approve: {str(e)}')
            approve_tx['gas'] = 65000

        estimated_gas_cost = approve_tx['gas'] * approve_tx['gasPrice']
        print(f'Оценочная стоимость газа для approve: {web3.from_wei(estimated_gas_cost, "ether")} ETH')
        if estimated_gas_cost > eth_balance:
            print(f'❌ Недостаточно ETH для газа approve!')
            return None

        signed_approve_tx = account.sign_transaction(approve_tx)
        approve_tx_hash = web3.eth.send_raw_transaction(signed_approve_tx.raw_transaction)
        print(f'Транзакция approve отправлена: https://basescan.org/tx/{approve_tx_hash.hex()}')

        try:
            receipt = web3.eth.wait_for_transaction_receipt(approve_tx_hash, timeout=120)
            if receipt['status'] == 1:
                print(f'✅ Транзакция approve выполнена: https://basescan.org/tx/{approve_tx_hash.hex()}')
            else:
                print(f'❌ Транзакция approve провалилась: https://basescan.org/tx/{approve_tx_hash.hex()}')
                print(f'Gas Used: {receipt["gasUsed"]} из {receipt["gasLimit"]}')
                tx = web3.eth.get_transaction(approve_tx_hash)
                try:
                    web3.eth.call(tx, block_identifier=receipt['blockNumber'])
                except ContractLogicError as e:
                    print(f'Причина ошибки: {str(e)}')
                return None
        except Exception as e:
            print(f'❌ Ошибка при проверке approve: {str(e)}')
            return None

    # Шаг 2: Получение котировки через API LI.FI
    url = "https://li.quest/v1/quote"
    params = {
        "fromChain": str(BASE_CHAIN_ID),
        "toChain": str(to_chain_id),
        "fromToken": from_token,
        "toToken": to_token,
        "fromAmount": str(amount_usdc),
        "fromAddress": wallet_address,
        "toAddress": wallet_address,
        "allowBridges": [bridge]
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {response.text[:500]}")
        print(f'❌ Ошибка API LI.FI: {response.text}')
        return None
    quote = response.json()
    print(f"Полный ответ API: {json.dumps(quote, indent=2)}")

    call_to = quote['transactionRequest']['to']
    call_data = quote['transactionRequest']['data']
    value = int(quote['transactionRequest']['value'], 16) if quote['transactionRequest']['value'].startswith('0x') else int(quote['transactionRequest']['value'])
    min_amount = int(quote['estimate']['toAmountMin'])
    print(f'callTo: {call_to}')
    print(f'callData: {call_data}')
    print(f'value: {web3.from_wei(value, "ether")} ETH')
    print(f'minAmount: {web3.from_wei(min_amount, "ether")} FTM')

    # Шаг 3: Подготовка и отправка транзакции
    nonce = web3.eth.get_transaction_count(wallet_address, 'pending')
    gas_price = web3.eth.gas_price * 2

    tx = {
        'from': wallet_address,
        'to': call_to,
        'value': value,
        'gasPrice': gas_price,
        'nonce': nonce,
        'data': call_data,
        'chainId': BASE_CHAIN_ID
    }

    try:
        estimated_gas = web3.eth.estimate_gas(tx)
        print(f'Оценка газа успешна: {estimated_gas} единиц')
        tx['gas'] = int(estimated_gas * 1.2)
    except Exception as e:
        print(f'Ошибка при оценке газа: {str(e)}')
        tx['gas'] = 600000

    estimated_gas_cost = tx['gas'] * tx['gasPrice']
    print(f'Оценочная стоимость газа для свопа: {web3.from_wei(estimated_gas_cost, "ether")} ETH')
    if estimated_gas_cost > eth_balance:
        print(f'❌ Недостаточно ETH для газа свопа!')
        return None

    signed_tx = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f'Транзакция свопа и бриджа отправлена: https://basescan.org/tx/{tx_hash.hex()}')

    try:
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt['status'] == 1:
            print(f'✅ Транзакция успешно выполнена: https://basescan.org/tx/{tx_hash.hex()}')
        else:
            print(f'❌ Транзакция провалилась: https://basescan.org/tx/{tx_hash.hex()}')
            print(f'Логи: {receipt}')
    except Exception as e:
        print(f'❌ Ошибка при проверке транзакции: {str(e)}')

    return tx_hash

# Пример использования в цикле
if __name__ == "__main__":
    # Список приватных ключей
    private_keys = [
        '',
        # Добавьте другие приватные ключи сюда, например:
        # 'другой_приватный_ключ_1',
        # 'другой_приватный_ключ_2',
    ]

    amount_usdc = 1000000  # 4 USDC

    for pk in private_keys:
        print(f"\nОбработка кошелька с приватным ключом: {pk[:6]}...{pk[-6:]}")
        tx_hash = swap_usdc_base_to_fantom(
            private_key=pk,
            amount_usdc=amount_usdc
        )
        if tx_hash:
            print(f"Успешно завершено для кошелька: {tx_hash.hex()}")
        else:
            print("Не удалось выполнить перевод для этого кошелька")