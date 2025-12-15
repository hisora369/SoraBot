# plugins/crypto_tool/crypto_tool.py
from ncatbot.plugin_system import NcatBotPlugin, command_registry
from ncatbot.plugin_system import param, option
from ncatbot.core.event import BaseMessageEvent
from ncatbot.utils import get_log
import base64
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes
import binascii

LOG = get_log("CryptoTool")


# 古典密码实现
class ClassicalCiphers:
    # 摩斯电码字典
    MORSE_CODE_DICT = {
        'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
        'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
        'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
        'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
        'Y': '-.--', 'Z': '--..',
        '0': '-----', '1': '.----', '2': '..---', '3': '...--', '4': '....-',
        '5': '.....', '6': '-....', '7': '--...', '8': '---..', '9': '----.',
        '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.',
        '!': '-.-.--', '/': '-..-.', '(': '-.--.', ')': '-.--.-',
        '&': '.-...', ':': '---...', ';': '-.-.-.', '=': '-...-',
        '+': '.-.-.', '-': '-....-', '_': '..--.-', '"': '.-..-.',
        '$': '...-..-', '@': '.--.-.', ' ': '/'
    }

    REVERSE_MORSE_DICT = {v: k for k, v in MORSE_CODE_DICT.items()}

    @staticmethod
    def morse_encrypt(text: str) -> str:
        """摩斯电码编码"""
        result = []
        text = text.upper()

        for char in text:
            if char in ClassicalCiphers.MORSE_CODE_DICT:
                result.append(ClassicalCiphers.MORSE_CODE_DICT[char])
            else:
                result.append(f"?[{char}]")

        return " ".join(result)

    @staticmethod
    def morse_decrypt(text: str) -> str:
        """摩斯电码解码"""
        result = []
        words = text.split('/')

        for word in words:
            letters = word.strip().split(' ')
            decoded_word = ""

            for letter in letters:
                if letter in ClassicalCiphers.REVERSE_MORSE_DICT:
                    decoded_word += ClassicalCiphers.REVERSE_MORSE_DICT[letter]
                elif letter:  # 非空字符串
                    decoded_word += f"?[{letter}]"

            result.append(decoded_word)

        return " ".join(result)

    @staticmethod
    def caesar_encrypt(text: str, shift: int = 3) -> str:
        result = []
        for char in text:
            if char.isalpha():
                ascii_offset = 65 if char.isupper() else 97
                result.append(chr((ord(char) - ascii_offset + shift) % 26 + ascii_offset))
            else:
                result.append(char)
        return "".join(result)

    @staticmethod
    def caesar_decrypt(text: str, shift: int = 3) -> str:
        return ClassicalCiphers.caesar_encrypt(text, -shift)

    @staticmethod
    def vigenere_encrypt(text: str, key: str) -> str:
        result = []
        key = key.upper()
        key_index = 0

        for char in text:
            if char.isalpha():
                ascii_offset = 65 if char.isupper() else 97
                shift = ord(key[key_index % len(key)]) - 65
                result.append(chr((ord(char) - ascii_offset + shift) % 26 + ascii_offset))
                key_index += 1
            else:
                result.append(char)
        return "".join(result)

    @staticmethod
    def vigenere_decrypt(text: str, key: str) -> str:
        result = []
        key = key.upper()
        key_index = 0

        for char in text:
            if char.isalpha():
                ascii_offset = 65 if char.isupper() else 97
                shift = ord(key[key_index % len(key)]) - 65
                result.append(chr((ord(char) - ascii_offset - shift) % 26 + ascii_offset))
                key_index += 1
            else:
                result.append(char)
        return "".join(result)


class CryptoToolPlugin(NcatBotPlugin):
    name = "CryptoTool"
    version = "1.0.0"
    dependencies = {}
    description = "密码学工具箱 - 支持古典密码、Base编码、哈希等"

    async def on_load(self):
        """插件加载时的初始化"""
        LOG.info("CryptoTool 插件已加载")

        # 设置默认配置
        self.register_config("aes_key", "default_key_123456")  # AES密钥
        self.register_config("enable_history", False)  # 是否记录历史

        # 支持的算法列表
        self.supported_algorithms = {
            "classical": ["caesar", "vigenere"],
            "modern": ["aes"],
            "hash": ["md5", "sha1", "sha256", "sha512", "blake2b"],
            "encode": ["base64", "base32", "base16"]
        }

    # 主命令组
    crypto_group = command_registry.group("crypto", description="🔐 密码学工具箱")

    @crypto_group.command("help", aliases=["h"], description="显示密码学工具帮助")
    async def help_cmd(self, event: BaseMessageEvent):
        help_text = """🔐 密码学工具箱使用指南 (CryptoTool)

📜 基础格式:
/crypto <命令> "文本内容" [算法/-a] [密钥/-k]

| 命令 | 描述 |
|:-----|:-----|
| help | 显示此帮助。 |
| encrypt| 加密文本。 |
| decrypt| 解密文本。 |
| hash | 计算哈希值。 |
| encode | Base/摩斯编码。 |
| decode | Base/摩斯解码。 |

🔑 常用示例：
# 凯撒加密 (默认: caesar, 移位=3)
/crypto encrypt "hello" 3
/crypto decrypt "khoor" -k 3

# 维吉尼亚加密
/crypto encrypt "text" -a vigenere -k KEY

# 摩斯电码
/crypto encode "SOS" -a morse
/crypto decode "... --- ..."

# 哈希计算 (默认: sha256)
/crypto hash "data"
/crypto hash "data" -a md5

# Base64 编码 (默认: base64)
/crypto encode "data"
/crypto decode "ZGF0YQ==" -a base64

⚠️ 注意:
1. "文本内容" 必须用引号括起来。
2. -a/-k 参数可选，用于指定算法或密钥。
        """
        await event.reply(help_text)

    @crypto_group.command("encrypt", description="加密文本")
    @param(name="algorithm", default="caesar", help="加密算法 (caesar/vigenere/aes/morse)")
    @param(name="key", default="3", help="密钥或移位值")
    async def encrypt_cmd(self, event: BaseMessageEvent, text: str, algorithm: str = "caesar", key: str = "3"):
        """加密命令"""
        try:
            result = await self._encrypt(algorithm.lower(), text, key)
            await event.reply(f"🔐 {algorithm.upper()} 加密结果：\n{result}")
        except Exception as e:
            await event.reply(f"❌ 加密失败：{str(e)}")

    @crypto_group.command("decrypt", description="解密文本")
    @param(name="algorithm", default="caesar", help="解密算法 (caesar/vigenere/aes/morse)")
    @param(name="key", default="3", help="密钥或移位值")
    async def decrypt_cmd(self, event: BaseMessageEvent, text: str, algorithm: str = "caesar", key: str = "3"):
        """解密命令"""
        try:
            result = await self._decrypt(algorithm.lower(), text, key)
            await event.reply(f"🔓 {algorithm.upper()} 解密结果：\n{result}")
        except Exception as e:
            await event.reply(f"❌ 解密失败：{str(e)}")

    @crypto_group.command("hash", description="计算哈希值")
    @param(name="algorithm", default="sha256", help="哈希算法")
    async def hash_cmd(self, event: BaseMessageEvent, text: str, algorithm: str = "sha256"):
        """哈希计算"""
        try:
            result = self._hash(algorithm.lower(), text)
            await event.reply(f"🧮 {algorithm.upper()} 哈希值：\n{result}")
        except Exception as e:
            await event.reply(f"❌ 哈希计算失败：{str(e)}")

    @crypto_group.command("encode", description="Base编码")
    @param(name="encoding_type", default="base64", help="编码类型 (base64/base32/base16)")
    async def encode_cmd(self, event: BaseMessageEvent, text: str, encoding_type: str = "base64"):
        """Base编码"""
        try:
            result = self._encode(encoding_type.lower(), text)
            await event.reply(f"🔀 {encoding_type.upper()} 编码结果：\n{result}")
        except Exception as e:
            await event.reply(f"❌ 编码失败：{str(e)}")

    @crypto_group.command("decode", description="Base解码")
    @param(name="encoding_type", default="base64", help="编码类型 (base64/base32/base16)")
    async def decode_cmd(self, event: BaseMessageEvent, text: str, encoding_type: str = "base64"):
        """Base解码"""
        try:
            result = self._decode(encoding_type.lower(), text)
            await event.reply(f"🔀 {encoding_type.upper()} 解码结果：\n{result}")
        except Exception as e:
            await event.reply(f"❌ 解码失败：{str(e)}")

    # 内部实现方法
    async def _encrypt(self, algorithm: str, text: str, key: str) -> str:
        """加密实现"""
        if algorithm == "caesar":
            shift = int(key)
            return ClassicalCiphers.caesar_encrypt(text, shift)

        elif algorithm == "vigenere":
            if not key or key == "3":
                raise ValueError("维吉尼亚密码需要提供密钥")
            return ClassicalCiphers.vigenere_encrypt(text, key)

        elif algorithm == "morse":
            return ClassicalCiphers.morse_encrypt(text)

        elif algorithm == "aes":
            # 使用插件配置中的密钥
            aes_key = self.config.get("aes_key", "default_key_123456")
            # 确保密钥长度为16/24/32字节
            aes_key = aes_key.ljust(16)[:16].encode('utf-8')

            cipher = AES.new(aes_key, AES.MODE_CBC)
            ct_bytes = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
            iv = binascii.hexlify(cipher.iv).decode('utf-8')
            ct = binascii.hexlify(ct_bytes).decode('utf-8')
            return f"{iv}:{ct}"

        else:
            raise ValueError(f"不支持的加密算法：{algorithm}")

    async def _decrypt(self, algorithm: str, text: str, key: str) -> str:
        """解密实现"""
        if algorithm == "caesar":
            shift = int(key)
            return ClassicalCiphers.caesar_decrypt(text, shift)

        elif algorithm == "vigenere":
            if not key or key == "3":
                raise ValueError("维吉尼亚密码需要提供密钥")
            return ClassicalCiphers.vigenere_decrypt(text, key)

        elif algorithm == "morse":
            return ClassicalCiphers.morse_decrypt(text)

        elif algorithm == "aes":
            # 使用插件配置中的密钥
            aes_key = self.config.get("aes_key", "default_key_123456")
            aes_key = aes_key.ljust(16)[:16].encode('utf-8')

            try:
                iv, ct = text.split(':')
                cipher = AES.new(aes_key, AES.MODE_CBC, binascii.unhexlify(iv))
                pt = unpad(cipher.decrypt(binascii.unhexlify(ct)), AES.block_size)
                return pt.decode('utf-8')
            except Exception as e:
                raise ValueError("解密失败，请检查密钥和密文格式")

        else:
            raise ValueError(f"不支持的解密算法：{algorithm}")

    def _hash(self, algorithm: str, text: str) -> str:
        """哈希计算"""
        if algorithm == "md5":
            return hashlib.md5(text.encode('utf-8')).hexdigest()
        elif algorithm == "sha1":
            return hashlib.sha1(text.encode('utf-8')).hexdigest()
        elif algorithm == "sha256":
            return hashlib.sha256(text.encode('utf-8')).hexdigest()
        elif algorithm == "sha512":
            return hashlib.sha512(text.encode('utf-8')).hexdigest()
        elif algorithm == "blake2b":
            return hashlib.blake2b(text.encode('utf-8')).hexdigest()
        else:
            raise ValueError(f"不支持的哈希算法：{algorithm}")

    def _encode(self, encoding_type: str, text: str) -> str:
        """Base编码"""
        if encoding_type == "base64":
            return base64.b64encode(text.encode('utf-8')).decode('utf-8')
        elif encoding_type == "base32":
            return base64.b32encode(text.encode('utf-8')).decode('utf-8')
        elif encoding_type == "base16":
            return base64.b16encode(text.encode('utf-8')).decode('utf-8')
        else:
            raise ValueError(f"不支持的编码类型：{encoding_type}")

    def _decode(self, encoding_type: str, text: str) -> str:
        """Base解码"""
        try:
            if encoding_type == "base64":
                return base64.b64decode(text.encode('utf-8')).decode('utf-8')
            elif encoding_type == "base32":
                return base64.b32decode(text.encode('utf-8')).decode('utf-8')
            elif encoding_type == "base16":
                return base64.b16decode(text.encode('utf-8')).decode('utf-8')
            else:
                raise ValueError(f"不支持的解码类型：{encoding_type}")
        except Exception as e:
            raise ValueError(f"解码失败，请检查输入格式：{str(e)}")

    async def on_close(self):
        """插件卸载时的清理"""
        LOG.info("CryptoTool 插件已卸载")

__all__ = ["CryptoToolPlugin"]