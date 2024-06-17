import requests
from fake_useragent import UserAgent
from loguru import logger
from web3 import Web3
import json

with open('contract_abi.json', 'r') as abi_file:
    contract_abi = json.load(abi_file)

with open('token_contract_abi.json', 'r') as abi_file:
    token_contract_abi = json.load(abi_file)

claim_contract_address = '0x66Fd4FC8FA52c9bec2AbA368047A0b27e24ecfe4'
token_contract_address = '0x5a7d6b2f92c77fad6ccabd7ee0624e64907eaf3e'
rpc_link = ""


def get_headers():
    ua = UserAgent()
    return {
        "Content-Type": 'application/json',
        "User-Agent": ua.random,
        "referer": 'https://claim.zknation.io/',
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://claim.zknation.io",
        "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "X-Api-Key": "46001d8f026d4a5bb85b33530120cd38"
    }


def get_eligibility(wallet_address, proxy):
    url = f'https://api.zknation.io/eligibility?id={wallet_address}'
    headers = get_headers()

    proxies = {
        'http': proxy,
        'https': proxy
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"An error occurred: {e}")
        return None


def load_data(file_path):
    with open(file_path, 'r') as file:
        return [line.strip() for line in file.readlines()]


def check_balance(account, web3):
    try:
        token_contract = web3.eth.contract(
            address=web3.to_checksum_address(token_contract_address),
            abi=token_contract_abi
        )
        balance = token_contract.functions.balanceOf(account.address).call()
        return balance
    except Exception as e:
        logger.error(f"Error checking balance for wallet {account.address}: {e}")
        return 0


def claim_tokens(account, key, eligibility_data, web3):
    try:
        allocation = eligibility_data['allocations'][0]
        token_amount = int(allocation['tokenAmount'])
        merkle_proof = allocation['merkleProof']
        merkle_index = int(allocation['merkleIndex'])

        contract = web3.eth.contract(address=web3.to_checksum_address(claim_contract_address), abi=contract_abi)

        transaction = contract.functions.claim(merkle_index, token_amount, merkle_proof).build_transaction({
            'from': account.address,
            'nonce': web3.eth.get_transaction_count(account.address),
            'gas': 1000000,
            'gasPrice': web3.to_wei('2', 'gwei')
        })

        signed_txn = web3.eth.account.sign_transaction(transaction, private_key=key)
        claim_txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
        logger.success(f'{account.address} | Claim transaction sent: https://era.zksync.network/tx/{claim_txn_hash.hex()}')

        web3.eth.wait_for_transaction_receipt(claim_txn_hash)
        return token_amount
    except Exception as e:
        logger.error(f"{account.address} | Error claiming tokens: {e}")
        return None


def transfer_tokens(account, key, token_amount, deposit_address, web3):
    try:
        token_contract = web3.eth.contract(
            address=web3.to_checksum_address(
            token_contract_address
        ),
            abi=token_contract_abi
        )
        transfer_transaction = token_contract.functions.transfer(
            web3.to_checksum_address(deposit_address),
            int(token_amount)
        ).build_transaction(
            {
                'from': account.address,
                'nonce': web3.eth.get_transaction_count(account.address),
                'gas': 500000,
                'gasPrice': web3.to_wei('2', 'gwei')
            })

        signed_transfer_txn = web3.eth.account.sign_transaction(
            transfer_transaction,
            private_key=key
        )
        transfer_txn_hash = web3.eth.send_raw_transaction(
            signed_transfer_txn.rawTransaction
        )
        logger.success(
            f'{account.address} | Transfer transaction sent: '
            f'https://era.zksync.network/tx/{transfer_txn_hash.hex()}')
    except Exception as e:
        logger.error(
            f"{account.address} | Error transferring tokens: {e}")


def process_wallet(key, proxy, deposit_address, web3):
    account = web3.eth.account.from_key(key)

    balance = check_balance(account, web3)
    if balance > 0:
        logger.info(f"{account.address} | Tokens already claimed, balance: {int(balance / 10 ** 18)} $ZK")
        transfer_tokens(account, key, balance, deposit_address, web3)
        return

    eligibility_data = get_eligibility(account.address, proxy)
    if not eligibility_data:
        logger.error(f"{account.address} | Failed to retrieve api data")
        return

    logger.success(f"{account.address} | Successfully retrieved data for claim")

    token_amount = claim_tokens(account, key, eligibility_data, web3)
    logger.success(f"{account.address} | Successfully claimed {int(token_amount / 10 ** 18)} $ZK")
  
    if token_amount is None:
        try:
            allocation = eligibility_data['allocations'][0]
            token_amount = int(allocation['tokenAmount'])
        except Exception as e:
            logger.error(f"{account.address} | Failed to retrieve token amount: {e}")
            return

    transfer_tokens(account, token_amount, key, deposit_address, web3)


if __name__ == "__main__":
    proxies = load_data('proxies.txt')
    wallets = load_data('private_keys.txt')
    deposits = load_data('deposit_addresses.txt')

    web3 = Web3(Web3.HTTPProvider(rpc_link))

    for private_key, proxy, deposit_address in zip(wallets, proxies, deposits):
        process_wallet(private_key, proxy, deposit_address, web3)
