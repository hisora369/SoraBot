# 导入所有插件模块
from plugins.sys import AlivePlugin, WalletPlugin, TTLCleanerPlugin
from plugins.interaction import InteractionPlugin, SignInPlugin
from plugins.game import NumberBombPlugin

__all__ = [
    'AlivePlugin',
    'SignInPlugin',
    'WalletPlugin',
    'TTLCleanerPlugin',
    'InteractionPlugin',
    'NumberBombPlugin'
]