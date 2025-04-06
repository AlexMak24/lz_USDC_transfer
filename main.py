import pandas as pd
from web3 import Web3
from function_bridge_usdc_to_arb import swap_max_usdc_fantom_to_arbitrum
from function_bridge_usdc_to_opt import swap_max_usdc_fantom_to_optimism
from buy_ftm_by_eth import swap_eth_base_to_fantom  # Импорт для перевода ETH в FTM

# Устанавливаем соединение с сетью Fantom
web3 = Web3(Web3.HTTPProvider('https://fantom-rpc.publicnode.com'))
if not web3.is_connected():
    raise Exception('❌ Не удалось подключиться к Fantom RPC')

# Адрес контракта lzUSDC
lz_usdc_address = '0x28a92dde19D9989F39A49905d7C9C2FAc7799bDf'

# ABI контракта lzUSDC
lz_usdc_abi = [
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function"
    }
]

# Функция для проверки баланса lzUSDC
def check_balance_lz_usdc(private_key):
    account_address = web3.eth.account.from_key(private_key).address
    contract = web3.eth.contract(address=lz_usdc_address, abi=lz_usdc_abi)
    balance = contract.functions.balanceOf(account_address).call()
    return balance

# Функция для проверки баланса FTM
def check_balance_ftm(private_key):
    account_address = web3.eth.account.from_key(private_key).address
    balance_wei = web3.eth.get_balance(account_address)
    balance_ftm = web3.from_wei(balance_wei, 'ether')  # Преобразуем wei в FTM
    return balance_ftm

def process_wallets(excel_file='wallets.xlsx'):
    # Чтение Excel-файла
    try:
        df = pd.read_excel(excel_file)
        print(f" Успешно загружен файл {excel_file}")
    except Exception as e:
        print(f" Ошибка при чтении файла {excel_file}: {str(e)}")
        return

    # Проверка структуры файла
    required_columns = ['PrivateKey', 'Amount', 'Arb', 'Optimism']
    if not all(col in df.columns for col in required_columns):
        print(f"❌ В файле {excel_file} отсутствуют необходимые столбцы: {required_columns}")
        return

    # Обработка каждого кошелька
    for index, row in df.iterrows():
        private_key = str(row['PrivateKey']).strip().replace("0x", "")  # Убираем префикс 0x
        amount_eth = float(row['Amount'])  # Сумма в ETH
        arb = int(row['Arb'])
        optimism = int(row['Optimism'])

        print(f"\n=== Обработка кошелька {index + 1} ===")
        print(f"Приватный ключ: {private_key[:6]}...{private_key[-6:]}")
        print(f"Сумма ETH: {amount_eth}")
        print(f"Arb: {arb}, Optimism: {optimism}")

        # Проверка валидности приватного ключа
        if not (len(private_key) == 64 and all(c in '0123456789abcdef' for c in private_key)):
            print(f"❌ Неверный формат приватного ключа: должен быть 64-символьной шестнадцатеричной строкой")
            continue

        # Проверка баланса lzUSDC
        balance_lz_usdc = check_balance_lz_usdc(private_key)
        if balance_lz_usdc == 0:
            print(f"❌ На кошельке {private_key[:6]}...{private_key[-6:]} нет lzUSDC (баланс 0), пропускаем его.")
            continue
        print(f"💰 Баланс lzUSDC: {balance_lz_usdc / 10**6:.2f} USDC")

        # Проверка баланса FTM
        balance_ftm = check_balance_ftm(private_key)
        print(f"💰 Баланс FTM: {balance_ftm:.6f} FTM")

        # Определение сети
        if arb == 1 and optimism == 0:
            network = 'arb'
        elif arb == 0 and optimism == 1:
            network = 'opt'
        else:
            print(f"❌ Неверный выбор сети: Arb={arb}, Optimism={optimism}. Должно быть только одно значение 1")
            continue

        # Шаг 1: Перевод ETH с Base на Fantom (получение FTM), если баланс FTM < 2
        if balance_ftm < 2:
            print(f"ℹ️ Баланс FTM меньше 2 ({balance_ftm:.6f} FTM), выполняем перевод ETH с Base на Fantom...")
            try:
                buy_ftm_tx = swap_eth_base_to_fantom(private_key, amount_eth)
                if buy_ftm_tx:
                    print(f"✅ Перевод ETH с Base на Fantom выполнен: {buy_ftm_tx.hex()}")
                else:
                    print(f"❌ Ошибка при переводе ETH с Base на Fantom")
                    continue
            except Exception as e:
                print(f"❌ Ошибка при переводе ETH с Base на Fantom: {str(e)}")
                continue
        else:
            print(f"ℹ️ Баланс FTM достаточен ({balance_ftm:.6f} FTM >= 2 FTM), пропускаем перевод ETH")

        # Шаг 2: Свап в выбранную сеть (Arbitrum или Optimism)
        try:
            if network == 'arb':
                swap_tx = swap_max_usdc_fantom_to_arbitrum(private_key)
            elif network == 'opt':
                swap_tx = swap_max_usdc_fantom_to_optimism(private_key)

            if swap_tx:
                print(f"✅ Свап в {network} выполнен: {swap_tx.hex()}")
            else:
                print(f"❌ Ошибка при свапе в {network}")
                continue
        except Exception as e:
            print(f"❌ Ошибка при свапе в {network}: {str(e)}")
            continue

    print("\n=== Обработка всех кошельков завершена ===")

if __name__ == "__main__":
    process_wallets('wallets.xlsx')
