import aiohttp
import json
from datetime import datetime
from gen_jwt import generate_jwt

import asyncio


api_host = "ng76x8yu9q.re.qweatherapi.com"
jwt_token = generate_jwt()

async def get_weather(location_id, days="3d"):
    # 替换为你的实际值
    YOUR_TOKEN = jwt_token
    YOUR_API_HOST = api_host

    url = f"https://{YOUR_API_HOST}/v7/weather/{days}"
    params = {
        "location": f"{location_id}",
    }
    headers = {
        "Authorization": f"Bearer {YOUR_TOKEN}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as response:
            # 检查响应状态
            response.raise_for_status()

            # 获取JSON格式的响应
            data = await response.json()
            print(data)

            # 或者获取文本响应
            # text = await response.text()
            # print(text)


asyncio.run(get_weather("101010100"))