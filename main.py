# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, PrivateMessage, GroupMessage

# ========== 创建 BotClient ==========
bot = BotClient()

# ========= 注册回调函数 ==========
# @bot.private_event()
# async def on_private_message(msg: PrivateMessage):
#     if msg.raw_message == "测试":
#         await bot.api.post_private_msg(msg.user_id, text="日日的空以成功启动")
#
# @bot.group_event()
# async def on_group_message(msg: GroupMessage):
#     if msg.raw_message == "测试":

#         await msg.reply("日日的空以成功启动")

# ========== 启动 BotClient==========
def main():
    bot.run_frontend()

if __name__ == "__main__":
    main()
