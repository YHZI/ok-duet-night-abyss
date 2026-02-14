import time
from typing import Protocol, Callable, Union
import numpy as np
import cv2
import winsound
import win32api
import win32con
import random
from collections import deque
import ctypes
from ctypes import wintypes

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import cached_property

from ok import BaseTask, Box, Logger, color_range_to_bound, og
from ok.device.intercation import GenshinInteraction, PyDirectInteraction
from ok.util.process import run_in_new_thread

logger = Logger.get_logger(__name__)
f_black_color = {
    'r': (0, 20),  # Red range
    'g': (0, 20),  # Green range
    'b': (0, 20)  # Blue range
}

# ============ 键盘和鼠标输入硬件伪装模块 ============
# 先定义 ctypes 结构体
class _KeyboardInput(ctypes.Structure):
    """键盘输入结构"""
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG))
    ]

class _MouseInput(ctypes.Structure):
    """鼠标输入结构"""
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG))
    ]

class _InputUnion(ctypes.Union):
    """输入联合体（支持键盘和鼠标）"""
    _fields_ = [
        ('ki', _KeyboardInput),
        ('mi', _MouseInput)
    ]

class _Input(ctypes.Structure):
    """INPUT 结构"""
    _anonymous_ = ('_input',)
    _fields_ = [
        ('type', wintypes.DWORD),
        ('_input', _InputUnion)
    ]

class KeyboardHardwareSpoofer:
    """键盘硬件信息伪装器 - 使用真实系统硬件标识符"""
    
    # Windows API 常量
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008
    INPUT_KEYBOARD = 1
    
    # 真实键盘硬件标识符（从系统获取）
    # Razer Huntsman V3 Pro Tenkeyless - HID\VID_1532&PID_02A7
    REAL_VENDOR_ID = 0x1532   # Razer
    REAL_PRODUCT_ID = 0x02A7  # Huntsman V3 Pro Tenkeyless
    
    def __init__(self):
        """初始化硬件伪装器"""
        self.user32 = ctypes.windll.user32
        self.SendInput = self.user32.SendInput
        self.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
        self.SendInput.restype = wintypes.UINT
        
        # 使用真实键盘的 VID:PID
        logger.info(f"[键盘伪装] 使用真实设备 Razer Huntsman V3 Pro (VID:0x{self.REAL_VENDOR_ID:04X}, PID:0x{self.REAL_PRODUCT_ID:04X})")
    
    def _generate_hardware_info(self):
        """生成真实硬件信息（使用系统真实 VID:PID）"""
        # 使用真实的 VID:PID 组合生成硬件信息
        # dwExtraInfo 格式: [VID(16bit)][PID(16bit)]
        # Windows HID 设备标识: VID_1532&PID_02A7
        hardware_info = (self.REAL_VENDOR_ID << 16) | self.REAL_PRODUCT_ID
        
        return hardware_info
    
    def _get_scan_code(self, vk_code):
        """获取虚拟键码对应的扫描码"""
        # 使用 MapVirtualKey 获取真实扫描码
        scan_code = self.user32.MapVirtualKeyW(vk_code, 0)  # MAPVK_VK_TO_VSC = 0
        
        # 为某些按键添加随机微调（模拟硬件差异）
        if random.random() < 0.05:  # 5% 概率添加微调
            scan_code = (scan_code & 0xFF) | random.choice([0, 0x0100])
        
        return scan_code
    
    def send_key_input(self, vk_code, is_down=True):
        """发送伪装的键盘输入（使用真实 Razer Huntsman 标识符）"""
        # 生成真实硬件信息
        hardware_info = self._generate_hardware_info()
        extra_info_value = wintypes.ULONG(hardware_info)
        
        # 获取扫描码
        scan_code = self._get_scan_code(vk_code)
        
        # 设置按键标志
        flags = 0
        if not is_down:
            flags |= self.KEYEVENTF_KEYUP
        
        # 对于扩展键（如方向键、Home、End 等）添加扩展标志
        extended_keys = [0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # Page/Arrow keys
                        0x2D, 0x2E, 0x2C,  # Insert, Delete, Print Screen
                        0x5B, 0x5C, 0x5D]  # Windows keys, App key
        if vk_code in extended_keys:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        
        # 构造输入结构
        kb_input = _KeyboardInput(
            wVk=vk_code,
            wScan=scan_code,
            dwFlags=flags,
            time=0,  # 系统自动填充时间戳
            dwExtraInfo=ctypes.pointer(extra_info_value)
        )
        
        input_struct = _Input(
            type=self.INPUT_KEYBOARD,
            ki=kb_input
        )
        
        # 发送输入
        result = self.SendInput(1, ctypes.pointer(input_struct), ctypes.sizeof(input_struct))
        
        if result == 0:
            logger.warning(f"[硬件伪装] SendInput 失败: VK={vk_code}, IsDown={is_down}")
            return False
        
        return True

# ============ 鼠标硬件伪装模块 ============
class MouseHardwareSpoofer:
    """鼠标硬件信息伪装器 - 使用真实系统硬件标识符"""
    
    # Windows API 常量
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000
    INPUT_MOUSE = 0
    
    # 真实鼠标硬件标识符（从系统获取）
    # Logitech Mouse - HID\VID_046D&PID_C547
    REAL_VENDOR_ID = 0x046D   # Logitech
    REAL_PRODUCT_ID = 0xC547  # Logitech Mouse/Keyboard Combo
    
    def __init__(self):
        """初始化鼠标硬件伪装器"""
        self.user32 = ctypes.windll.user32
        self.SendInput = self.user32.SendInput
        self.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
        self.SendInput.restype = wintypes.UINT
        
        # 获取屏幕尺寸（用于绝对坐标转换）
        self.screen_width = self.user32.GetSystemMetrics(0)
        self.screen_height = self.user32.GetSystemMetrics(1)
        
        # 记录上次鼠标位置（用于相对移动）
        self.last_mouse_pos = None
        
        logger.info(f"[鼠标伪装] 使用真实设备 Logitech (VID:0x{self.REAL_VENDOR_ID:04X}, PID:0x{self.REAL_PRODUCT_ID:04X})")
    
    def _generate_hardware_info(self):
        """生成真实硬件信息（使用系统真实 VID:PID）"""
        # 使用真实的 VID:PID 组合生成硬件信息
        # dwExtraInfo 格式: [VID(16bit)][PID(16bit)]
        # Windows HID 设备标识: VID_046D&PID_C547
        hardware_info = (self.REAL_VENDOR_ID << 16) | self.REAL_PRODUCT_ID
        
        return hardware_info
    
    def _add_micro_jitter(self, x, y):
        """添加微抖动（模拟真实人手抖动）"""
        # 5% 概率添加 1-2 像素的微抖动
        if random.random() < 0.05:
            jitter_x = random.randint(-2, 2)
            jitter_y = random.randint(-2, 2)
            return x + jitter_x, y + jitter_y
        return x, y
    
    def move_mouse_absolute(self, x, y):
        """移动鼠标到绝对屏幕坐标（使用真实 Logitech 标识符）"""
        # 添加微抖动
        x, y = self._add_micro_jitter(x, y)
        
        # 生成真实硬件信息
        hardware_info = self._generate_hardware_info()
        extra_info_value = wintypes.ULONG(hardware_info)
        
        # 将屏幕坐标转换为绝对坐标（0-65535）
        abs_x = int((x * 65535) / self.screen_width)
        abs_y = int((y * 65535) / self.screen_height)
        
        # 构造鼠标输入
        mouse_input = _MouseInput(
            dx=abs_x,
            dy=abs_y,
            mouseData=0,
            dwFlags=self.MOUSEEVENTF_MOVE | self.MOUSEEVENTF_ABSOLUTE,
            time=0,
            dwExtraInfo=ctypes.pointer(extra_info_value)
        )
        
        input_struct = _Input(
            type=self.INPUT_MOUSE,
            mi=mouse_input
        )
        
        result = self.SendInput(1, ctypes.pointer(input_struct), ctypes.sizeof(input_struct))
        
        if result == 0:
            logger.warning(f"[鼠标伪装] SendInput MOVE 失败: ({x}, {y})")
            return False
        
        self.last_mouse_pos = (x, y)
        return True
    
    def click_mouse(self, button='left', down_time=0.05):
        """执行鼠标点击（带硬件伪装）"""
        # 生成硬件信息
        hardware_info = self._generate_hardware_info()
        extra_info_value = wintypes.ULONG(hardware_info)
        
        # 确定按键标志
        if button == 'left':
            down_flag = self.MOUSEEVENTF_LEFTDOWN
            up_flag = self.MOUSEEVENTF_LEFTUP
        elif button == 'right':
            down_flag = self.MOUSEEVENTF_RIGHTDOWN
            up_flag = self.MOUSEEVENTF_RIGHTUP
        elif button == 'middle':
            down_flag = self.MOUSEEVENTF_MIDDLEDOWN
            up_flag = self.MOUSEEVENTF_MIDDLEUP
        else:
            return False
        
        # 按下鼠标
        mouse_down = _MouseInput(
            dx=0, dy=0, mouseData=0,
            dwFlags=down_flag,
            time=0,
            dwExtraInfo=ctypes.pointer(extra_info_value)
        )
        
        input_down = _Input(type=self.INPUT_MOUSE, mi=mouse_down)
        result = self.SendInput(1, ctypes.pointer(input_down), ctypes.sizeof(input_down))
        
        if result == 0:
            logger.warning(f"[鼠标伪装] SendInput {button} DOWN 失败")
            return False
        
        # 按住时间（模拟人手按压）
        if down_time > 0:
            time.sleep(down_time)
        
        # 释放鼠标（使用新的硬件信息）
        hardware_info_up = self._generate_hardware_info()
        extra_info_value_up = wintypes.ULONG(hardware_info_up)
        
        mouse_up = _MouseInput(
            dx=0, dy=0, mouseData=0,
            dwFlags=up_flag,
            time=0,
            dwExtraInfo=ctypes.pointer(extra_info_value_up)
        )
        
        input_up = _Input(type=self.INPUT_MOUSE, mi=mouse_up)
        result = self.SendInput(1, ctypes.pointer(input_up), ctypes.sizeof(input_up))
        
        if result == 0:
            logger.warning(f"[鼠标伪装] SendInput {button} UP 失败")
            return False
        
        return True
    
    def move_and_click(self, x, y, button='left', down_time=0.05):
        """移动并点击（完整事件序列）"""
        # 先移动到目标位置
        if not self.move_mouse_absolute(x, y):
            return False
        
        # 短暂延迟（模拟人手反应时间）
        time.sleep(random.uniform(0.01, 0.03))
        
        # 执行点击
        return self.click_mouse(button, down_time)

# 全局硬件伪装器实例（延迟初始化）
_keyboard_spoofer = None
_mouse_spoofer = None

def get_keyboard_spoofer():
    """获取全局键盘硬件伪装器实例"""
    global _keyboard_spoofer
    if _keyboard_spoofer is None:
        _keyboard_spoofer = KeyboardHardwareSpoofer()
    return _keyboard_spoofer

def get_mouse_spoofer():
    """获取全局鼠标硬件伪装器实例"""
    global _mouse_spoofer
    if _mouse_spoofer is None:
        _mouse_spoofer = MouseHardwareSpoofer()
    return _mouse_spoofer

# 兼容旧接口
def get_hardware_spoofer():
    """获取键盘硬件伪装器（兼容旧代码）"""
    return get_keyboard_spoofer()
# ============ 键盘和鼠标硬件伪装模块结束 ============

class Ticker(Protocol):
    """
    技能循环计时器接口。
    
    这是一个可调用的对象（类似函数），用于控制动作的执行频率，
    并提供了额外的方法来手动干预计时器的状态。
    """
    
    def __call__(self) -> None:
        """
        尝试执行动作（Tick）。
        
        如果距离上次执行的时间超过了设定的间隔（Interval），
        则执行绑定的 Action，并更新最后执行时间。
        """
        ...

    def reset(self) -> None:
        """
        重置计时器状态。
        
        将“上次执行时间”归零。这意味着下一次调用 tick() 时，
        几乎肯定会立即触发动作（视为初次运行）。
        """
        ...

    def touch(self) -> None:
        """
        刷新计时器（将最后执行时间设为当前时间）。
        
        用于“欺骗”计时器刚刚执行过动作。
        效果：强制动作进入冷却，直到经过一个完整的 interval 周期。
        """
        ...

    def start_next_tick(self) -> None:
        """
        重置下一帧的计时起点（同步延迟）。
        
        标记计时器。下一次调用 tick() 时，不会检查间隔，也不会执行动作，
        而是直接将“上次执行时间”对齐到那一刻的时间。
        
        用途：通常用于在手动释放技能后，告诉计时器从下一帧开始重新倒计时。
        """
        ...

class BaseDNATask(BaseTask):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.key_config = self.get_global_config('Game Hotkey Config')  # 游戏热键配置
        self.monthly_card_config = self.get_global_config('Monthly Card Config')
        self.afk_config = self.get_global_config('挂机设置')
        self.old_mouse_pos = None
        self.next_monthly_card_start = 0
        self._logged_in = False
        self.enable_fidget_action = True
        self.fidget_params = {"hold_lalt": False, "skip_jitter": False, "mouse_lock": False}
        self.sensitivity_config = self.get_global_config('Game Sensitivity Config')  # 游戏灵敏度配置
        self.onetime_seen = set()
        self.onetime_queue = deque()

    @property
    def f_search_box(self) -> Box:
        f_search_box = self.get_box_by_name('pick_up_f')
        f_search_box = f_search_box.copy(x_offset=f_search_box.width * 3.25,
                                         width_offset=f_search_box.width * 0.65,
                                         height_offset=f_search_box.height * 8.7,
                                         y_offset=-f_search_box.height * 1.7,
                                         name='search_dialog')
        return f_search_box

    @property
    def thread_pool_executor(self) -> ThreadPoolExecutor:
        if og.my_app is None:
            return None
        return og.my_app.get_thread_pool_executor()

    def submit_periodic_task(self, delay, task, *args, **kwargs):
        if og.my_app is None:
            return None
        return og.my_app.submit_periodic_task(delay, task, *args, **kwargs)
    
    @property
    def shared_frame(self) -> np.ndarray:
        return og.my_app.shared_frame
    
    @shared_frame.setter
    def shared_frame(self, value):
        og.my_app.shared_frame = value

    @cached_property
    def genshin_interaction(self):
        """
        缓存 Interaction 实例，避免每次鼠标移动都重新创建对象。
        需要确保 self.executor.interaction 和 self.hwnd 在此类初始化时可用。
        """
        # 确保引用的是正确的类
        return GenshinInteraction(self.executor.interaction.capture, self.hwnd)
    
    @cached_property
    def pydirect_interaction(self):
        """
        缓存 Interaction 实例，避免每次鼠标移动都重新创建对象。
        需要确保 self.executor.interaction 和 self.hwnd 在此类初始化时可用。
        """
        # 确保引用的是正确的类
        return PyDirectInteraction(self.executor.interaction.capture, self.hwnd)
    
    def enable(self):
        self.onetime_seen = set()
        super().enable()

    def log_onetime_info(self, msg: str, key=None|str):
        if key is None:
            key = msg
        if key in self.onetime_seen:
            return
        self.onetime_seen.add(key)
        self.log_info(msg)
        if len(self.onetime_queue) > 100:
            oldest_msg = self.onetime_queue.popleft()
            self.onetime_seen.discard(oldest_msg)

    def in_team(self, frame=None) -> bool:
        _frame = self.frame if frame is None else frame
        if self.find_one('lv_text', frame=frame, threshold=0.8):
            return True
        # start_time = time.perf_counter()
        mat = self.get_feature_by_name("ultimate_key_icon").mat
        mat2 = self.box_of_screen(0.8832, 0.9132, 0.8977, 0.9389, name="ultimate_key_icon", hcenter=True).crop_frame(_frame)
        max_area1 = invert_max_area_only(mat)[2]
        max_area2 = invert_max_area_only(mat2)[2]
        result = False
        if max_area1 > 0:
            if abs(max_area1 - max_area2) / max_area1 < 0.15:
                result = True
        # elapsed = time.perf_counter() - start_time
        # logger.debug(f"in_team check took {elapsed:.4f} seconds.")
        return result

    def in_team_and_world(self):
        return self.in_team()

    def ensure_main(self, esc=True, time_out=30):
        self.info_set('current task', 'wait main')
        if not self.wait_until(lambda: self.is_main(esc=esc), time_out=time_out, raise_if_not_found=False):
            raise Exception('Please start in game world and in team!')
        self.info_set('current task', 'in main')

    def is_main(self, esc=True):
        if self.in_team():
            self._logged_in = True
            return True
        if self.handle_monthly_card():
            return True
        # if self.wait_login():
        #     return True
        if esc:
            self.back(after_sleep=1.5)

    def find_start_btn(self, threshold: float = 0, box: Box | None = None, template=None) -> Box | None:
        if isinstance(box, Box):
            self.draw_boxes(box.name, box, "blue")
        return self.find_one('start_icon', threshold=threshold, box=box, template=template)

    def find_cancel_btn(self, threshold: float = 0, box: Box | None = None, template=None) -> Box | None:
        if isinstance(box, Box):
            self.draw_boxes(box.name, box, "blue")
        return self.find_one('cancel_icon', threshold=threshold, box=box, template=template)

    def find_retry_btn(self, threshold: float = 0, box: Box | None = None, template=None) -> Box | None:
        if isinstance(box, Box):
            self.draw_boxes(box.name, box, "blue")
        return self.find_one('retry_icon', threshold=threshold, box=box, template=template)

    def find_quit_btn(self, threshold: float = 0, box: Box | None = None, template=None) -> Box | None:
        if isinstance(box, Box):
            self.draw_boxes(box.name, box, "blue")
        return self.find_one('quit_icon', threshold=threshold, box=box, template=template)

    def find_drop_item(self, rates=2000, threshold: float = 0, box: Box | None = None, template=None) -> Box | None:
        if isinstance(box, Box):
            self.draw_boxes(box.name, box, "blue")
        else:
            box = self.box_of_screen(0.381, 0.406, 0.713, 0.483, name="drop_rate_item", hcenter=True)
        return self.find_one(f'drop_item_{str(rates)}', threshold=threshold, box=box, template=template)

    def find_not_use_letter_icon(self, threshold: float = 0, box: Box | None = None, template=None) -> Box | None:
        if isinstance(box, Box):
            self.draw_boxes(box.name, box, "blue")
        else:
            box = self.box_of_screen(0.4552, 0.3954, 0.4927, 0.4648, name="not_use_letter", hcenter=True)
        return self.find_one('not_use_letter', threshold=threshold, box=box, template=template)

    def safe_get(self, key, default=None):
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def soundBeep(self, _n=None):
        if not self.afk_config.get("提示音", True):
            return
        if _n is None:
            n = max(1, self.afk_config.get("提示音次数", 1))
        else:
            n = _n
        run_in_new_thread(
            lambda: [winsound.Beep(523, 150) or time.sleep(0.3) for _ in range(n)]
        )

    def log_info_notify(self, msg):
        self.log_info(msg, notify=self.afk_config['弹出通知'])

    def move_mouse_to_safe_position(self, save_current_pos: bool = True, boxes: Union[list[Box], Box, None] = None):
        if self.afk_config["防止鼠标干扰"]:
            self.old_mouse_pos = win32api.GetCursorPos() if save_current_pos else None
            if self.rel_move_if_in_win(0.95, 0.6, boxes=boxes):
                pass
            else:
                self.old_mouse_pos = None

    def move_back_from_safe_position(self):
        if self.afk_config["防止鼠标干扰"] and self.old_mouse_pos is not None:
            win32api.SetCursorPos(self.old_mouse_pos)
            self.old_mouse_pos = None

    # def sleep(self, timeout):
    #     return super().sleep(timeout - self.check_for_monthly_card())

    def check_for_monthly_card(self):
        if self.should_check_monthly_card():
            start = time.time()
            ret = self.handle_monthly_card()
            cost = time.time() - start
            return ret, cost
            # start = time.time()
            # logger.info(f'check_for_monthly_card start check')
            # if self.in_combat():
            #     logger.info(f'check_for_monthly_card in combat return')
            #     return time.time() - start
            # if self.in_team():
            #     logger.info(f'check_for_monthly_card in team send sleep until monthly card popup')
            #     monthly_card = self.wait_until(self.handle_monthly_card, time_out=120, raise_if_not_found=False)
            #     logger.info(f'wait monthly card end {monthly_card}')
            #     cost = time.time() - start
            #     return cost
        return False, 0

    def should_check_monthly_card(self):
        if self.next_monthly_card_start > 0:
            if 0 < time.time() - self.next_monthly_card_start < 120:
                return True
        return False

    def set_check_monthly_card(self, next_day=False):
        if self.monthly_card_config.get('Check Monthly Card'):
            now = datetime.now()
            hour = self.monthly_card_config.get('Monthly Card Time')
            # Calculate the next 5 o'clock in the morning
            next_four_am = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if now >= next_four_am or next_day:
                next_four_am += timedelta(days=1)
            next_monthly_card_start_date_time = next_four_am - timedelta(seconds=30)
            # Subtract 1 minute from the next 5 o'clock in the morning
            self.next_monthly_card_start = next_monthly_card_start_date_time.timestamp()
            logger.info('set next monthly card start time to {}'.format(next_monthly_card_start_date_time))
        else:
            self.next_monthly_card_start = 0
            logger.info('set next monthly card start to {}'.format(self.next_monthly_card_start))

    def handle_monthly_card(self):
        monthly_card = self.find_one('monthly_card', threshold=0.8)
        if not hasattr(self, '_last_monthly_card_check_time'):
            self._last_monthly_card_check_time = 0
        now = time.time()
        if now - self._last_monthly_card_check_time >= 10:
            self._last_monthly_card_check_time = now
            self.screenshot('monthly_card1')
        ret = monthly_card is not None
        if ret:
            self.wait_until(self.in_team, time_out=10,
                            post_action=lambda: self.click_relative(0.50, 0.89, after_sleep=1))
            self.set_check_monthly_card(next_day=True)
        logger.info(f'check_monthly_card {monthly_card}, ret {ret}')
        return ret

    def find_track_point(self, threshold: float = 0, box: Box | None = None, template=None, frame_processor=None,
                         mask_function=None, filter_track_color=False) -> Box | None:
        frame = None
        if box is None:
            box = self.box_of_screen_scaled(2560, 1440, 454, 265, 2110, 1094, name="find_track_point", hcenter=True)
        # if isinstance(box, Box):
        #     self.draw_boxes(box.name, box, "blue")
        if filter_track_color:
            if template is None:
                template = self.get_feature_by_name("track_point").mat
            template = color_filter(template, track_point_color)
            frame = color_filter(self.frame, track_point_color)
        return self.find_one("track_point", threshold=threshold, box=box, template=template, frame=frame,
                             frame_processor=frame_processor, mask_function=mask_function)

    def is_mouse_in_window(self) -> bool:
        """
        检测鼠标是否在游戏窗口范围内。

        Returns:
            bool: 如果鼠标在窗口内则返回 True，否则返回 False。
        """
        mouse_x, mouse_y = win32api.GetCursorPos()
        hwnd_window = og.device_manager.hwnd_window
        win_x = hwnd_window.x - (hwnd_window.window_width - hwnd_window.width)
        win_y = hwnd_window.y - (hwnd_window.window_height - hwnd_window.height)

        return (win_x <= mouse_x < win_x + hwnd_window.window_width) and \
            (win_y <= mouse_y < win_y + hwnd_window.window_height)
    
    def set_mouse_in_window(self, use_trajectory=True):
        """
        设置鼠标在游戏窗口范围内。
        
        参数:
            use_trajectory: 是否使用贝塞尔曲线轨迹移动
        """
        if self.is_mouse_in_window():
            return
        random_x = random.randint(self.width_of_screen(0.2), self.width_of_screen(0.8))
        random_y = random.randint(self.height_of_screen(0.2), self.height_of_screen(0.8))
        
        if use_trajectory:
            # 前台和后台都使用贝塞尔曲线移动
            self.move_mouse_with_trajectory(random_x, random_y)
        else:
            # 仅当明确禁用轨迹时直接移动
            abs_pos = self.executor.interaction.capture.get_abs_cords(random_x, random_y)
            win32api.SetCursorPos(abs_pos)

    def _generate_bezier_curve(self, start_x, start_y, end_x, end_y, num_points=None):
        """
        生成带波动的贝塞尔曲线轨迹点，模拟真实人手移动
        
        参数:
            start_x, start_y: 起始坐标
            end_x, end_y: 目标坐标
            num_points: 轨迹点数量，None则根据距离自动计算
        
        返回: [(x1,y1), (x2,y2), ...] 轨迹点列表
        """
        # 计算距离
        distance = ((end_x - start_x)**2 + (end_y - start_y)**2)**0.5
        
        # 根据距离自动计算点数（每25像素约1个点，增加点数使曲线更平滑）
        if num_points is None:
            num_points = max(8, min(60, int(distance / 25)))
        
        # 计算移动方向的垂直向量（用于添加侧向波动）
        dx = end_x - start_x
        dy = end_y - start_y
        if distance > 0:
            # 归一化方向向量
            norm_dx = dx / distance
            norm_dy = dy / distance
            # 垂直向量（逆时针旋转90度）
            perp_x = -norm_dy
            perp_y = norm_dx
        else:
            perp_x, perp_y = 0, 0
        
        # 生成多个控制点使用三次贝塞尔曲线（更自然的曲线）
        # 控制点1：靠近起点
        ctrl1_offset = random.uniform(0.2, 0.35)  # 在路径的20%-35%位置
        ctrl1_x = start_x + dx * ctrl1_offset
        ctrl1_y = start_y + dy * ctrl1_offset
        
        # 控制点2：靠近终点
        ctrl2_offset = random.uniform(0.65, 0.8)  # 在路径的65%-80%位置
        ctrl2_x = start_x + dx * ctrl2_offset
        ctrl2_y = start_y + dy * ctrl2_offset
        
        # 为两个控制点添加随机偏移（垂直于移动方向）
        offset_range = distance * random.uniform(0.1, 0.25)
        
        # 控制点1的偏移（可能向左或向右）
        lateral_offset1 = random.uniform(-offset_range, offset_range)
        ctrl1_x += perp_x * lateral_offset1
        ctrl1_y += perp_y * lateral_offset1
        
        # 控制点2的偏移（倾向与控制点1相反方向，形成S型或C型曲线）
        if random.random() > 0.5:
            # 50%概率形成S型曲线
            lateral_offset2 = -lateral_offset1 * random.uniform(0.3, 0.8)
        else:
            # 50%概率形成C型曲线
            lateral_offset2 = lateral_offset1 * random.uniform(0.5, 1.0)
        
        ctrl2_x += perp_x * lateral_offset2
        ctrl2_y += perp_y * lateral_offset2
        
        # 生成三次贝塞尔曲线的基础点
        points = []
        
        # 随机生成波动参数
        wave_frequency = random.uniform(1.5, 3.5)  # 波动频率
        wave_amplitude = distance * random.uniform(0.005, 0.02)  # 波动幅度
        
        for i in range(num_points):
            t = i / (num_points - 1)
            
            # 三次贝塞尔曲线公式
            # B(t) = (1-t)³P₀ + 3(1-t)²tP₁ + 3(1-t)t²P₂ + t³P₃
            t_inv = 1 - t
            
            # 基础贝塞尔曲线坐标
            x = (t_inv**3 * start_x + 
                 3 * t_inv**2 * t * ctrl1_x + 
                 3 * t_inv * t**2 * ctrl2_x + 
                 t**3 * end_x)
            
            y = (t_inv**3 * start_y + 
                 3 * t_inv**2 * t * ctrl1_y + 
                 3 * t_inv * t**2 * ctrl2_y + 
                 t**3 * end_y)
            
            # 添加正弦波动模拟人手抖动（在移动中间部分波动更明显）
            if 0.1 < t < 0.9:  # 起点和终点附近不添加太多波动
                wave_t = t * wave_frequency * 3.14159  # 波动相位
                wave_intensity = 4 * t * (1 - t)  # 中间部分波动最大
                
                # 垂直于移动方向的波动
                wave_offset = np.sin(wave_t) * wave_amplitude * wave_intensity
                x += perp_x * wave_offset
                y += perp_y * wave_offset
                
                # 添加小的随机抖动
                jitter = wave_amplitude * 0.5
                x += random.uniform(-jitter, jitter)
                y += random.uniform(-jitter, jitter)
            
            points.append((int(x), int(y)))
        
        # 去除重复的连续点（优化轨迹）
        optimized_points = [points[0]]
        for i in range(1, len(points)):
            if points[i] != optimized_points[-1]:
                optimized_points.append(points[i])
        
        return optimized_points

    def move_mouse_with_trajectory(self, target_x, target_y, duration=None, save_original_pos=False):
        """
        沿贝塞尔曲线轨迹移动鼠标到目标位置
        
        参数:
            target_x, target_y: 目标位置（游戏窗口相对坐标）
            duration: 移动总时长（秒），None则根据距离自动计算
            save_original_pos: 是否保存原始鼠标位置（用于后续复原）
        
        返回:
            如果save_original_pos=True，返回原始鼠标位置(x, y)，否则返回None
        """
        # 锁定鼠标，暂停 fidget_action 的鼠标抖动
        self.fidget_params["mouse_lock"] = True
        
        try:
            # 获取当前鼠标位置
            current_pos = win32api.GetCursorPos()
            original_pos = current_pos if save_original_pos else None
            
            # 转换目标位置为绝对坐标
            target_abs = self.executor.interaction.capture.get_abs_cords(int(target_x), int(target_y))
            
            # 计算距离
            distance = ((target_abs[0] - current_pos[0])**2 + (target_abs[1] - current_pos[1])**2)**0.5
            
            # 如果距离太小，直接移动
            if distance < 5:
                win32api.SetCursorPos(target_abs)
                return original_pos
            
            # 根据距离自动计算移动时长（每200像素约0.2秒）
            if duration is None:
                duration = max(0.1, min(0.5, distance / 1000))
            
            # 生成贝塞尔曲线轨迹
            trajectory = self._generate_bezier_curve(
                current_pos[0], current_pos[1],
                target_abs[0], target_abs[1]
            )
            
            # 沿轨迹移动，使用变速（加速-匀速-减速）模拟真实人手移动
            points_count = len(trajectory)
            
            # 判断是否使用硬件伪装（前台模式）
            use_hardware_spoof = self.hwnd.is_foreground()
            if use_hardware_spoof:
                try:
                    mouse_spoofer = get_mouse_spoofer()
                except Exception as e:
                    logger.warning(f"[鼠标伪装] 初始化失败，使用 SetCursorPos: {e}")
                    use_hardware_spoof = False
            
            for i, (x, y) in enumerate(trajectory):
                # 使用硬件伪装或普通移动
                if use_hardware_spoof:
                    try:
                        mouse_spoofer.move_mouse_absolute(int(x), int(y))
                    except Exception as e:
                        logger.warning(f"[鼠标伪装] SendInput 失败，回退到 SetCursorPos: {e}")
                        win32api.SetCursorPos((int(x), int(y)))
                        use_hardware_spoof = False
                else:
                    win32api.SetCursorPos((int(x), int(y)))
                
                # 计算当前进度（0到1）
                progress = i / (points_count - 1) if points_count > 1 else 1
                
                # 使用缓动函数计算延迟（模拟加速减速）
                # 开始慢速加速，中间快速，末尾减速
                if progress < 0.2:
                    # 起始阶段：较慢（加速）
                    delay_factor = 2.5 - progress * 5
                elif progress > 0.85:
                    # 结束阶段：减速至较慢
                    delay_factor = 1.0 + (progress - 0.85) * 8
                else:
                    # 中间阶段：快速移动
                    delay_factor = 0.3 + random.uniform(-0.1, 0.1)
                
                # 基础延迟时间
                base_interval = duration / points_count
                actual_interval = base_interval * delay_factor
                
                # 添加微小随机延迟模拟人手不稳定
                jitter = actual_interval * random.uniform(-0.15, 0.15)
                final_interval = max(0.001, actual_interval + jitter)
                
                if i < points_count - 1:  # 最后一个点不需要延迟
                    time.sleep(final_interval)
            
            return original_pos
        finally:
            # 无论如何都要解锁鼠标，允许 fidget_action 重新抖动
            self.fidget_params["mouse_lock"] = False
    
    def restore_mouse_position(self, original_pos, use_trajectory=True):
        """
        复原鼠标到原始位置
        
        参数:
            original_pos: 原始鼠标位置(x, y)，如果为None则不执行任何操作
            use_trajectory: 是否使用贝塞尔曲线轨迹移动回去
        """
        if original_pos is None:
            return
        
        current_pos = win32api.GetCursorPos()
        
        # 计算距离，如果太近就不需要复原
        distance = ((original_pos[0] - current_pos[0])**2 + (original_pos[1] - current_pos[1])**2)**0.5
        if distance < 5:
            return
        
        if use_trajectory:
            # 使用贝塞尔曲线轨迹移动回去
            duration = max(0.1, min(0.5, distance / 1000))
            trajectory = self._generate_bezier_curve(
                current_pos[0], current_pos[1],
                original_pos[0], original_pos[1]
            )
            
            points_count = len(trajectory)
            
            # 判断是否使用硬件伪装
            use_hardware_spoof = self.hwnd.is_foreground()
            if use_hardware_spoof:
                try:
                    mouse_spoofer = get_mouse_spoofer()
                except Exception:
                    use_hardware_spoof = False
            
            for i, (x, y) in enumerate(trajectory):
                # 使用硬件伪装或普通移动
                if use_hardware_spoof:
                    try:
                        mouse_spoofer.move_mouse_absolute(int(x), int(y))
                    except Exception:
                        win32api.SetCursorPos((int(x), int(y)))
                        use_hardware_spoof = False
                else:
                    win32api.SetCursorPos((int(x), int(y)))
                
                # 使用变速逻辑
                progress = i / (points_count - 1) if points_count > 1 else 1
                
                if progress < 0.2:
                    delay_factor = 2.5 - progress * 5
                elif progress > 0.85:
                    delay_factor = 1.0 + (progress - 0.85) * 8
                else:
                    delay_factor = 0.3 + random.uniform(-0.1, 0.1)
                
                base_interval = duration / points_count
                actual_interval = base_interval * delay_factor
                jitter = actual_interval * random.uniform(-0.15, 0.15)
                final_interval = max(0.001, actual_interval + jitter)
                
                if i < points_count - 1:
                    time.sleep(final_interval)
        else:
            # 直接移动回去
            win32api.SetCursorPos(original_pos)
    
    def move_mouse_abs_with_trajectory(self, target_abs_x, target_abs_y, duration=None):
        """
        使用贝塞尔曲线轨迹移动鼠标到绝对坐标位置（屏幕坐标）
        
        参数:
            target_abs_x, target_abs_y: 目标位置（屏幕绝对坐标）
            duration: 移动总时长（秒），None则根据距离自动计算
        """
        # 获取当前鼠标位置
        current_pos = win32api.GetCursorPos()
        
        # 计算距离
        distance = ((target_abs_x - current_pos[0])**2 + (target_abs_y - current_pos[1])**2)**0.5
        
        # 如果距离太小，直接移动
        if distance < 5:
            win32api.SetCursorPos((target_abs_x, target_abs_y))
            return
        
        # 根据距离自动计算移动时长
        if duration is None:
            duration = max(0.1, min(0.5, distance / 1000))
        
        # 生成贝塞尔曲线轨迹
        trajectory = self._generate_bezier_curve(
            current_pos[0], current_pos[1],
            target_abs_x, target_abs_y
        )
        
        # 沿轨迹移动，使用变速模拟真实人手移动
        points_count = len(trajectory)
        
        for i, (x, y) in enumerate(trajectory):
            win32api.SetCursorPos((int(x), int(y)))
            
            # 使用缓动函数计算延迟（加速-匀速-减速）
            progress = i / (points_count - 1) if points_count > 1 else 1
            
            if progress < 0.2:
                delay_factor = 2.5 - progress * 5
            elif progress > 0.85:
                delay_factor = 1.0 + (progress - 0.85) * 8
            else:
                delay_factor = 0.3 + random.uniform(-0.1, 0.1)
            
            base_interval = duration / points_count
            actual_interval = base_interval * delay_factor
            jitter = actual_interval * random.uniform(-0.15, 0.15)
            final_interval = max(0.001, actual_interval + jitter)
            
            if i < points_count - 1:
                time.sleep(final_interval)
    
    def _perform_random_click(self, x_abs, y_abs, use_safe_move=False, safe_move_box: Union[list[Box], Box, None]=None, down_time=0.0, post_sleep=0.0, after_sleep=0.0, use_trajectory=True, restore_position=False):
        """
        执行带随机延迟和轨迹移动的点击操作
        
        参数:
            x_abs, y_abs: 目标点击位置（游戏窗口相对坐标）
            use_safe_move: 后台点击时是否使用安全移动（已弃用，后台也会移动鼠标）
            safe_move_box: 安全移动区域（已弃用）
            down_time: 鼠标按下时长
            post_sleep: 点击前延迟
            after_sleep: 点击后延迟
            use_trajectory: 是否使用贝塞尔曲线轨迹移动（前台和后台都支持）
            restore_position: 是否在点击后复原鼠标位置
        """
        x = int(x_abs)
        y = int(y_abs)

        _post_sleep = 0.0 if post_sleep <= 0 else post_sleep + random.uniform(0.05, 0.15)
        _down_time = random.uniform(0.06, 0.13) if down_time <= 0 else max(0.05, down_time + random.uniform(0.0, 0.13))
        _after_sleep = random.uniform(0.01, 0.04) if after_sleep <= 0 else after_sleep + random.uniform(0.02, 0.08)
        
        # 锁定鼠标，暂停 fidget_action 的鼠标抖动
        self.fidget_params["mouse_lock"] = True
        
        self.sleep(_post_sleep)

        original_pos = None
        
        if not self.hwnd.is_foreground():
            # 后台模式：也支持轨迹移动，使行为更真实
            if use_trajectory:
                original_pos = self.move_mouse_with_trajectory(x, y, save_original_pos=restore_position)
                self.sleep(random.uniform(0.05, 0.08))
            else:
                if restore_position:
                    original_pos = win32api.GetCursorPos()
                # 直接移动到目标位置
                abs_pos = self.executor.interaction.capture.get_abs_cords(x, y)
                win32api.SetCursorPos(abs_pos)
                self.sleep(random.uniform(0.08, 0.12))
            
            # 使用PostMessage点击
            self.click(x, y, down_time=_down_time)
        else:
            # 前台模式：使用硬件伪装点击
            if use_trajectory:
                original_pos = self.move_mouse_with_trajectory(x, y, save_original_pos=restore_position)
                self.sleep(random.uniform(0.05, 0.08))
            else:
                if restore_position:
                    original_pos = win32api.GetCursorPos()
                self.pydirect_interaction.move(x, y)
                self.sleep(random.uniform(0.08, 0.12))
            
            # 尝试使用鼠标硬件伪装点击
            try:
                mouse_spoofer = get_mouse_spoofer()
                # 添加随机抖动到按下时长
                actual_down_time = _down_time + random.uniform(-0.01, 0.02)
                actual_down_time = max(0.03, actual_down_time)
                
                success = mouse_spoofer.click_mouse('left', actual_down_time)
                if not success:
                    # 硬件伪装失败，回退到 PyDirectInteraction
                    self.pydirect_interaction.click(down_time=_down_time)
            except Exception as e:
                logger.warning(f"[鼠标伪装] 点击失败，使用备用方法: {e}")
                self.pydirect_interaction.click(down_time=_down_time)
        
        self.sleep(_after_sleep)
        
        # 如果需要，复原鼠标位置
        if restore_position and original_pos is not None:
            self.restore_mouse_position(original_pos, use_trajectory=use_trajectory)
        
        # 释放鼠标锁，恢复 fidget_action 的鼠标抖动
        self.fidget_params["mouse_lock"] = False

    def click_btn_random(self, box: Box, safe_move_box: Box = None, down_time=0.0, post_sleep=0.0, after_sleep=0.0):
        _safe_move_box = box.copy(x_offset=-box.width*0.20, width_offset=box.width * 8.1,
                                 y_offset=-box.height*0.30, height_offset=box.height * 0.7, name='safe_move_box')
        
        x_range = [box.x + box.width, box.x + self.width * 0.12]
        y_range = [box.y, box.y + box.height]
        random_x = random.uniform(x_range[0], x_range[1])
        random_y = random.uniform(y_range[0], y_range[1])

        random_box = self.box_of_screen_scaled(self.width, self.height, int(x_range[0]), int(y_range[0]), int(x_range[1]), int(y_range[1]), name="random_box", hcenter=True)
        self.draw_boxes(random_box.name, random_box, "blue")
        
        if safe_move_box is not None:
            if isinstance(safe_move_box, Box):
                safe_move_box = [safe_move_box]
            safe_move_box.append(_safe_move_box)
        else:
            safe_move_box = _safe_move_box

        self._perform_random_click(
            random_x, random_y, 
            use_safe_move=True,
            safe_move_box=safe_move_box, 
            down_time=down_time,
            post_sleep=post_sleep,
            after_sleep=after_sleep
        )
    
    def click_box_random(self, box: Box, down_time=0.0, post_sleep=0.0, after_sleep=0.0, use_safe_move=False, safe_move_box=None, left_extend=0.0, right_extend=0.0, up_extend=0.0, down_extend=0.0):
        le_px = left_extend * self.width
        re_px = right_extend * self.width
        ue_px = up_extend * self.height
        de_px = down_extend * self.height

        x_range = [box.x - le_px, box.x + box.width + re_px]
        y_range = [box.y - ue_px, box.y + box.height + de_px]
        random_x = random.uniform(x_range[0], x_range[1])
        random_y = random.uniform(y_range[0], y_range[1])

        random_box = self.box_of_screen_scaled(self.width, self.height, int(x_range[0]), int(y_range[0]), int(x_range[1]), int(y_range[1]), name="random_box", hcenter=True)
        self.draw_boxes(random_box.name, random_box, "blue")

        self._perform_random_click(
            random_x, random_y, 
            use_safe_move=use_safe_move,
            safe_move_box=safe_move_box, 
            down_time=down_time,
            post_sleep=post_sleep,
            after_sleep=after_sleep
        )

    def click_relative_random(self, x1, y1, x2, y2, down_time=0.0, post_sleep=0.0, after_sleep=0.0, use_safe_move=False, safe_move_box=None):
        r_x = random.uniform(x1, x2)
        r_y = random.uniform(y1, y2)

        abs_x = self.width_of_screen(r_x)
        abs_y = self.height_of_screen(r_y)

        self._perform_random_click(
            abs_x, abs_y, 
            use_safe_move=use_safe_move,
            safe_move_box=safe_move_box, 
            down_time=down_time,
            post_sleep=post_sleep,
            after_sleep=after_sleep
        )

    def sleep_random(self, timeout, random_range: tuple = (1.0, 1.0)):
        multiplier = random.uniform(random_range[0], random_range[1])
        final_timeout = timeout * multiplier
        self.sleep(final_timeout)

    def is_mouse_in_box(self, box: Box) -> bool:
        """
        检测鼠标是否在给定的 Box 内。

        Args:
            box (Box): 给定的 Box。

        Returns:
            bool: 如果鼠标在 Box 内则返回 True，否则返回 False。
        """
        if not isinstance(box, Box):
            return True
        mouse_x, mouse_y = win32api.GetCursorPos()
        hwnd_window = og.device_manager.hwnd_window
        coords = [
            (box.x, box.y),
            (box.x + box.width, box.y + box.height)
        ]
        (x1, y1), (x2, y2) = [hwnd_window.get_abs_cords(x, y) for x, y in coords]
        return x1 <= mouse_x < x2 and y1 <= mouse_y < y2

    def rel_move_if_in_win(self, x=0.5, y=0.5, boxes: Union[list[Box], Box, None] = None, use_trajectory=True):
        """
        如果鼠标在窗口内，则将其移动到游戏窗口内的相对位置。

        Args:
            x (float): 相对 x 坐标 (0.0 到 1.0)。
            y (float): 相对 y 坐标 (0.0 到 1.0)。
            boxes: 边界框限制，如果鼠标不在指定框内则不移动
            use_trajectory: 是否使用贝塞尔曲线轨迹移动
        """
        if not self.is_mouse_in_window():
            return False
        if isinstance(boxes, Box):
            boxes = [boxes]
        if boxes is not None:
            self.draw_boxes("safe_move_box", boxes, "blue")
            for box in boxes:
                if self.is_mouse_in_box(box=box):
                    break
            else:
                return False
        
        target_x = self.width_of_screen(x)
        target_y = self.height_of_screen(y)
        
        if use_trajectory:
            # 前台和后台都使用贝塞尔曲线移动
            self.move_mouse_with_trajectory(target_x, target_y)
        else:
            # 仅当明确禁用轨迹时直接移动
            abs_pos = self.executor.device_manager.hwnd_window.get_abs_cords(target_x, target_y)
            win32api.SetCursorPos(abs_pos)
        return True

    def create_ticker(self, action: Callable, interval: Union[float, int, Callable] = 1.0, interval_random_range: tuple = (1.0, 1.0)) -> Ticker:
        last_time = 0
        armed = False

        def get_interval():
            if callable(interval):
                return interval()
            if hasattr(interval, "value"):
                return interval.value
            return float(interval)

        def tick():
            nonlocal last_time, armed
            now = time.perf_counter()

            if armed:
                last_time = now
                armed = False
                return

            multiplier = random.uniform(interval_random_range[0], interval_random_range[1])
            current_interval = get_interval() * multiplier

            if last_time < 0 or now - last_time >= current_interval:
                last_time = now
                action()

        def reset():
            nonlocal last_time
            last_time = -1

        def touch():
            nonlocal last_time
            last_time = time.perf_counter()

        def start_next_tick():
            nonlocal armed
            armed = True

        tick.reset = reset
        tick.touch = touch
        tick.start_next_tick = start_next_tick
        return tick
    
    def create_ticker_group(self, tickers: list):
    
        def tick_all():
            for ticker in tickers:
                ticker()
                
        def reset_all():
            for ticker in tickers:
                if hasattr(ticker, "reset"):
                    ticker.reset()

        def touch_all():
            for ticker in tickers:
                if hasattr(ticker, "touch"):
                    ticker.touch()

        def start_next_tick_all():
            for ticker in tickers:
                if hasattr(ticker, "start_next_tick"):
                    ticker.start_next_tick()

        tick_all.reset = reset_all
        tick_all.touch = touch_all
        tick_all.start_next_tick = start_next_tick_all
        
        return tick_all

    def get_interact_key(self):
        """获取交互的按键。

        Returns:
            str: 交互的按键字符串。
        """
        return self.key_config['Interact Key']

    def get_dodge_key(self):
        """获取闪避的按键。

        Returns:
            str: 闪避的按键字符串。
        """
        return self.key_config['Dodge Key']

    def get_spiral_dive_key(self):
        """获取螺旋飞跃的按键。

        Returns:
            str: 螺旋飞跃的按键字符串。
        """
        return self.key_config['HelixLeap Key']
        
    def calculate_sensitivity(self, dx, dy, use_aim_sensitivity=False, original_Xsensitivity=1.0, original_Ysensitivity=1.0):
        """计算玩家水平鼠标移动值和垂直鼠标移动值,并且移动鼠标.

        Returns:
            int: 玩家水平鼠标移动值
            int: 玩家垂直鼠标移动值

        """
        # 判断设置中灵敏度开关是否打开
        if self.sensitivity_config['Game Sensitivity Switch']:
            # 获取设置中的游戏灵敏度
            if not use_aim_sensitivity:
                game_Xsensitivity = self.sensitivity_config['X-axis sensitivity']
                game_Ysensitivity = self.sensitivity_config['Y-axis sensitivity']
            else:
                game_Xsensitivity = self.sensitivity_config['Aim X-axis sensitivity']
                game_Ysensitivity = self.sensitivity_config['Aim Y-axis sensitivity']

            # 判断和计算
            if original_Xsensitivity == game_Xsensitivity and original_Ysensitivity == game_Ysensitivity:
                calculate_dx = dx
                calculate_dy = dy
            else:
                calculate_dx = round(dx / (game_Xsensitivity / original_Xsensitivity))
                calculate_dy = round(dy / (game_Ysensitivity / original_Ysensitivity))
        else:
            calculate_dx = dx
            calculate_dy = dy

        return calculate_dx, calculate_dy

    def move_mouse_relative(self, dx, dy, use_aim_sensitivity=False, original_Xsensitivity=1.0, original_Ysensitivity=1.0):
        dx, dy = self.calculate_sensitivity(dx, dy, use_aim_sensitivity, original_Xsensitivity, original_Ysensitivity)
        self.try_bring_to_front()
        self.genshin_interaction.move_mouse_relative(int(dx), int(dy))

    def try_bring_to_front(self):
        if not self.hwnd.is_foreground():
            def key_press(key, after_sleep=0):
                win32api.keybd_event(key, 0, 0, 0)
                win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
                self.sleep(after_sleep)

            key_press(win32con.VK_MENU)
            try:
                self.hwnd.bring_to_front()
            except Exception:
                key_press(win32con.VK_LWIN, 0.1)
                key_press(win32con.VK_LWIN, 0.1)
                key_press(win32con.VK_MENU)
                self.hwnd.bring_to_front()
            self.sleep(0.5)
        
    def setup_fidget_action(self):
        if not self.enable_fidget_action:
            return

        lalt_pressed = False
        needs_resync = False

        def send_key_raw(key, is_down):
            """发送键盘信号（优先使用硬件伪装）"""
            interaction = self.executor.interaction
            vk_code = interaction.get_key_by_str(key)
            
            # 优先使用硬件伪装的 SendInput（前台窗口时）
            if self.hwnd.is_foreground():
                try:
                    spoofer = get_hardware_spoofer()
                    success = spoofer.send_key_input(vk_code, is_down)
                    if success:
                        return
                except Exception as e:
                    logger.warning(f"[硬件伪装] 失败，回退到 PostMessage: {e}")
            
            # 回退到 PostMessage（后台或硬件伪装失败时）
            event = win32con.WM_KEYDOWN if is_down else win32con.WM_KEYUP
            lparam = interaction.make_lparam(vk_code)
            interaction.post(event, vk_code, lparam)

        def get_magic_sleep_time():
            """
            核心防检测逻辑：
            生成针对 Lua 0.3s 量化刻度的随机时间。
            目标刻度: 0.0s, 0.3s, 0.6s, 0.9s
            """
            return random.choice([
                random.uniform(0.005, 0.02),
                random.uniform(0.20, 0.28),
                random.uniform(0.50, 0.58),
                random.uniform(0.80, 0.88)
            ])

        def in_team():
            if self.shared_frame is None:
                return True
            return self.in_team(self.shared_frame)

        def check_alt_logic():
            nonlocal lalt_pressed, needs_resync
            
            if not self.afk_config.get("鼠标抖动", True):
                return

            if self.fidget_params.get("hold_lalt", False):
                if not lalt_pressed:
                    self.log_info("[LAlt保持] 激活: 按下 LAlt")
                    send_key_raw("lalt", True)
                    time.sleep(0.1)
                    lalt_pressed = True
                elif not needs_resync and lalt_pressed and not in_team():
                    wait_time = get_magic_sleep_time()
                    time.sleep(wait_time)
                    self.log_info("[LAlt保持] 暂停: 检测到不在队伍，暂时释放 LAlt")
                    needs_resync = True
                    send_key_raw("lalt", False)
                elif needs_resync and in_team():
                    self.log_info("[LAlt保持] 恢复: 检测到重回队伍，重新按下 LAlt")
                    needs_resync = False
                    time.sleep(0.2)
                    send_key_raw("lalt", True)
            else:
                if lalt_pressed:
                    self.log_info("[LAlt保持] 停止: 功能关闭，彻底释放 LAlt")
                    send_key_raw("lalt", False)
                    lalt_pressed = False
                    needs_resync = False

        def perform_mouse_jitter(current_drift):
            """执行鼠标微小抖动，返回更新后的漂移量"""
            # 检查鼠标锁：如果主线程正在执行点击操作，则跳过抖动
            if self.fidget_params.get("mouse_lock", False):
                return current_drift
            
            if not self.afk_config.get("鼠标抖动", True) or self.fidget_params.get("skip_jitter", False):
                return current_drift

            if self.afk_config.get("鼠标抖动锁定在窗口范围", True):
                self.set_mouse_in_window()

            dist_sq = current_drift[0]**2 + current_drift[1]**2

            if dist_sq < 4:
                target_x = random.choice([-3, -2, 2, 3])
                target_y = random.choice([-3, -2, 2, 3])
            else:
                target_x = random.randint(-1, 1)
                target_y = random.randint(-1, 1)

            move_x = target_x - current_drift[0]
            move_y = target_y - current_drift[1]

            if move_x == 0 and move_y == 0:
                move_x = 1 if random.random() > 0.5 else -1

            self.genshin_interaction.do_move_mouse_relative(move_x, move_y)
            
            current_drift[0] += move_x
            current_drift[1] += move_y
            
            return current_drift

        def perform_random_key_press(key_list):
            """执行随机按键，包含核心的防检测时间逻辑"""

            key = random.choice(key_list)
            
            human_down_time = random.uniform(0.02, 0.09)
            
            magic_after_sleep = get_magic_sleep_time()

            send_key_raw(key, True)
            time.sleep(human_down_time)
            send_key_raw(key, False)
            
            time.sleep(magic_after_sleep)

        def smart_sleep(duration):
            deadline = time.time() + duration
            while time.time() < deadline:
                if self.executor.current_task is None or self.executor.exit_event.is_set():
                    return False

                check_alt_logic()
                time.sleep(0.1)
            return True

        def _fidget_worker():
            current_drift = [0, 0]

            excluded_keys = {
                self.get_spiral_dive_key(), 
                self.key_config.get('Ultimate Key'), 
                self.key_config.get('Combat Key')
            }
            numeric_keys = [str(i) for i in range(1, 7) if str(i) not in excluded_keys][:4]
            random_key_list = [self.key_config['Geniemon Key']] + numeric_keys

            if self.executor.current_task:
                self.log_info("fidget action started")

            while self.executor.current_task is not None and not self.executor.exit_event.is_set():
                if self.executor.paused:
                    time.sleep(0.1)
                    continue

                check_alt_logic()

                current_drift = perform_mouse_jitter(current_drift)

                perform_random_key_press(random_key_list)

                long_sleep = random.choice([
                    random.uniform(3.05, 3.20), # ~ 3.0 / 3.3
                    random.uniform(4.25, 4.40), # ~ 4.2 / 4.5
                    random.uniform(5.45, 5.60)  # ~ 5.4 / 5.7
                ])
                
                if not smart_sleep(long_sleep):
                    break
                    
            self.log_debug("fidget action stopped")

        self.thread_pool_executor.submit(_fidget_worker)

track_point_color = {
    "r": (121, 255),  # Red range
    "g": (116, 255),  # Green range
    "b": (34, 211),  # Blue range
}

lower_white = np.array([244, 244, 244], dtype=np.uint8)
lower_white_none_inclusive = np.array([243, 243, 243], dtype=np.uint8)
upper_white = np.array([255, 255, 255], dtype=np.uint8)
black = np.array([0, 0, 0], dtype=np.uint8)


def isolate_white_text_to_black(cv_image):
    """
    Converts pixels in the near-white range (244-255) to black,
    and all others to white.
    Args:
        cv_image: Input image (NumPy array, BGR).
    Returns:
        Black and white image (NumPy array), where matches are black.
    """
    match_mask = cv2.inRange(cv_image, black, lower_white_none_inclusive)
    output_image = cv2.cvtColor(match_mask, cv2.COLOR_GRAY2BGR)

    return output_image


def color_filter(img, color):
    lower_bound, upper_bound = color_range_to_bound(color)
    mask = cv2.inRange(img, lower_bound, upper_bound)
    img_modified = img.copy()
    img_modified[mask == 0] = 0
    return img_modified


def invert_max_area_only(mat):
    # 转灰度并二值化
    gray = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY)

    # 连通组件分析
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(thresh)

    # 找最大连通区域（排除背景）
    areas = stats[1:, 4]
    if len(areas) == 0:
        return None, None, 0
    # max_area = np.max(areas)
    max_idx = np.argmax(areas) + 1

    # 生成只包含最大区域的掩码
    max_region = (labels == max_idx).astype(np.uint8) * 255

    # 对这个区域做黑白反转，其他部分全部置为0
    inverted_region = 255 - max_region

    # 再计算反转后的最大白色区域（一般只有一块）
    num_labels2, labels2, stats2, centroids2 = cv2.connectedComponentsWithStats(inverted_region)
    areas2 = stats2[1:, 4]
    if len(areas2) == 0:
        return None, None, 0
    max_area2 = np.max(areas2)
    max_idx2 = np.argmax(areas2) + 1

    # 提取最终掩码
    final_mask = (labels2 == max_idx2).astype(np.uint8) * 255

    return inverted_region, final_mask, max_area2
