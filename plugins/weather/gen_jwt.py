#!/usr/bin/env python3
import sys
import time
import jwt


def generate_jwt() -> str:
    # print("Generating JWT...")
    # Open PEM
    with open("D:/SoraBot/ncatbot/plugins/weather/ed25519-private.pem", "r") as f:
        private_key = f.read()

    payload = {
        'iat': int(time.time()) - 30,
        'exp': int(time.time()) + 900,
        'sub': '4KKQ7T2BGA'
    }
    headers = {
        'kid': 'T6B8E2TRQ2'
    }

    encoded_jwt = jwt.encode(payload, private_key, algorithm='EdDSA', headers=headers)
    return encoded_jwt


if __name__ == "__main__":
    jwt_token = generate_jwt()
    print(f"{jwt_token}")
    with open("jwt.txt", "w") as f:
        f.write(jwt_token)