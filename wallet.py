from eth_account import Account

class Wallet:
    def __init__(self, private_key, amount, arb_flag, optimism_flag, destination_address):
        """
        :param private_key: Приватный ключ кошелька
        :param amount: Количество токенов для перевода (в wei)
        :param arb_flag: Флаг для Arbitrum (0 или 1)
        :param optimism_flag: Флаг для Optimism (0 или 1)
        :param destination_address: Адрес для отправки на Base
        """
        self.private_key = private_key
        self.amount = amount
        self.arb_flag = arb_flag
        self.optimism_flag = optimism_flag
        self.destination_address = destination_address
        self.account = Account.from_key(private_key)
        self.wallet_address = self.account.address

    def __str__(self):
        return (f"Wallet: {self.wallet_address}, Amount: {self.amount / 10**6} USDC, "
                f"Arb: {self.arb_flag}, Optimism: {self.optimism_flag}, Dest: {self.destination_address}")