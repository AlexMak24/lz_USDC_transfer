import json
import requests
from web3 import Web3
from eth_account import Account
from web3.exceptions import ContractLogicError

# Конфигурация глобальных констант
BASE_RPC = 'https://mainnet.base.org'
ETH_ADDRESS = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # ETH
LIFI_CONTRACT_ADDRESS = Web3.to_checksum_address('0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE')
BASE_CHAIN_ID = 8453  # Base
FANTOM_CHAIN_ID = 250  # Fantom
FTM_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"  # FTM на Fantom

def swap_eth_base_to_fantom(private_key, amount_eth, rpc_url=BASE_RPC, from_token=ETH_ADDRESS, to_chain_id=FANTOM_CHAIN_ID, to_token=FTM_TOKEN_ADDRESS, bridge="squid"):
    """
    Переводит ETH с Base на Fantom через LI.FI, получая FTM.

    :param private_key: Приватный ключ кошелька
    :param amount_eth: Количество ETH для перевода (например, 0.002 ETH)
    :param rpc_url: URL RPC для Base (по умолчанию 'https://mainnet.base.org')
    :param from_token: Адрес токена на Base (по умолчанию ETH)
    :param to_chain_id: Chain ID сети назначения (по умолчанию 250 для Fantom)
    :param to_token: Адрес токена на сети назначения (по умолчанию FTM)
    :param bridge: Используемый мост (по умолчанию "squid")
    :return: Хэш транзакции или None в случае ошибки
    """
    # Преобразование amount_eth в amount_eth_wei (1 ETH = 10^18 wei)
    try:
        amount_eth_wei = int(amount_eth * 10**18)
    except (ValueError, TypeError) as e:
        print(f"❌ Ошибка при преобразовании суммы ETH в wei: {str(e)}")
        return None
    print(f"Сумма для перевода: {amount_eth} ETH ({amount_eth_wei} wei)")

    # Инициализация аккаунта
    try:
        account = Account.from_key(private_key)
    except ValueError as e:
        print(f"❌ Ошибка при инициализации аккаунта: {str(e)}")
        return None
    wallet_address = account.address
    print(f"\n▶️ Адрес кошелька: {wallet_address}")

    # Подключение к Base
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        print(f'❌ Не удалось подключиться к Base RPC: {rpc_url}')
        return None
    print('✅ Успешно подключено к Base RPC')

    # Проверка баланса ETH
    eth_balance = web3.eth.get_balance(wallet_address)
    eth_balance_in_ether = web3.from_wei(eth_balance, 'ether')
    print(f'Баланс ETH на адресе {wallet_address}: {eth_balance_in_ether} ETH')
    if eth_balance < amount_eth_wei:
        print(f'❌ Недостаточно ETH! Требуется: {web3.from_wei(amount_eth_wei, "ether")} ETH, доступно: {eth_balance_in_ether}')
        return None

    # Шаг 1: Получение котировки через API LI.FI
    url = "https://li.quest/v1/quote"
    params = {
        "fromChain": str(BASE_CHAIN_ID),
        "toChain": str(to_chain_id),
        "fromToken": from_token,
        "toToken": to_token,
        "fromAmount": str(amount_eth_wei),
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

    # Шаг 2: Подготовка и отправка транзакции
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
    total_eth_needed = value + estimated_gas_cost
    if total_eth_needed > eth_balance:
        print(f'❌ Недостаточно ETH! Требуется: {web3.from_wei(total_eth_needed, "ether")} ETH (value + gas), доступно: {eth_balance_in_ether}')
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
        '',
    ]

    amount_eth = 0.001  # Теперь вводим сумму в ETH (например, 0.001 ETH)

    for pk in private_keys:
        print(f"\nОбработка кошелька с приватным ключом: {pk[:6]}...{pk[-6:]}")
        tx_hash = swap_eth_base_to_fantom(
            private_key=pk,
            amount_eth=amount_eth
        )
        if tx_hash:
            print(f"Успешно завершено для кошелька: {tx_hash.hex()}")
        else:
            print("Не удалось выполнить перевод для этого кошелька")
