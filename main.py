import pandas as pd
from web3 import Web3
from function_bridge_usdc_to_arb import swap_max_usdc_fantom_to_arbitrum
from function_bridge_usdc_to_opt import swap_usdc_fantom_to_optimism
from buy_ftm_by_eth import swap_eth_base_to_fantom  # Импорт для перевода ETH в FTM

def process_wallets(excel_file='wallets.xlsx'):
    # Чтение Excel-файла
    try:
        df = pd.read_excel(excel_file)
        print(f"✅ Успешно загружен файл {excel_file}")
    except Exception as e:
        print(f"❌ Ошибка при чтении файла {excel_file}: {str(e)}")
        return

    # Проверка структуры файла
    required_columns = ['PrivateKey', 'Amount', 'Arb', 'Optimism', 'Destination']
    if not all(col in df.columns for col in required_columns):
        print(f"❌ В файле {excel_file} отсутствуют необходимые столбцы: {required_columns}")
        return

    # Обработка каждого кошелька
    for index, row in df.iterrows():
        private_key = str(row['PrivateKey']).strip()
        amount_eth = float(row['Amount'])  # Сумма в ETH
        arb = int(row['Arb'])
        optimism = int(row['Optimism'])
        destination_address = str(row['Destination']).strip()

        print(f"\n=== Обработка кошелька {index + 1} ===")
        print(f"Приватный ключ: {private_key[:6]}...{private_key[-6:]}")
        print(f"Сумма ETH: {amount_eth}")
        print(f"Arb: {arb}, Optimism: {optimism}")
        print(f"Адрес назначения: {destination_address}")

        # Проверка валидности приватного ключа
        if not (len(private_key) == 64 and all(c in '0123456789abcdef' for c in private_key)):
            print(f"❌ Неверный формат приватного ключа: должен быть 64-символьной шестнадцатеричной строкой")
            continue

        # Проверка валидности адреса назначения
        try:
            Web3.to_checksum_address(destination_address)
        except ValueError:
            print(f"❌ Неверный формат адреса назначения: {destination_address}")
            continue

        # Определение сети
        if arb == 1 and optimism == 0:
            network = 'arb'
        elif arb == 0 and optimism == 1:
            network = 'opt'
        else:
            print(f"❌ Неверный выбор сети: Arb={arb}, Optimism={optimism}. Должно быть только одно значение 1")
            continue

        # Шаг 1: Перевод ETH с Base на Fantom (получение FTM)
        try:
            buy_ftm_tx = swap_eth_base_to_fantom(private_key, amount_eth)  # Передаем amount_eth напрямую
            if buy_ftm_tx:
                print(f"✅ Перевод ETH с Base на Fantom выполнен: {buy_ftm_tx.hex()}")
            else:
                print(f"❌ Ошибка при переводе ETH с Base на Fantom")
                continue
        except Exception as e:
            print(f"❌ Ошибка при переводе ETH с Base на Fantom: {str(e)}")
            continue

        # Шаг 2: Свап в выбранную сеть (Arbitrum или Optimism)
        try:
            if network == 'arb':
                swap_tx = swap_max_usdc_fantom_to_arbitrum(private_key)
            elif network == 'opt':
                swap_tx = swap_usdc_fantom_to_optimism(private_key)

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
