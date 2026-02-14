import ok
from src.config import config

if __name__ == '__main__':
    # Monkey patch: 给 BrowserWindowAdapter 添加 exe_full_path 属性以兼容 WGC
    try:
        from ok.device.capture import BrowserWindowAdapter
        import os
        
        if not hasattr(BrowserWindowAdapter, '_exe_full_path_patched'):
            # 原始初始化方法
            original_init = BrowserWindowAdapter.__init__
            
            def patched_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                # 尝试获取浏览器的实际路径
                try:
                    import psutil
                    # 假设浏览器窗口有 hwnd 属性
                    if hasattr(self, 'hwnd') and self.hwnd:
                        import win32process
                        import win32gui
                        _, pid = win32process.GetWindowThreadProcessId(self.hwnd)
                        proc = psutil.Process(pid)
                        self.exe_full_path = proc.exe()
                    else:
                        # 默认使用 Edge 路径
                        self.exe_full_path = os.path.join(
                            os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
                            'Microsoft', 'Edge', 'Application', 'msedge.exe'
                        )
                except Exception:
                    # 回退到硬编码路径
                    self.exe_full_path = 'msedge.exe'
            
            BrowserWindowAdapter.__init__ = patched_init
            BrowserWindowAdapter._exe_full_path_patched = True
            print("[Monkey Patch] BrowserWindowAdapter.exe_full_path 已添加")
    except Exception as e:
        print(f"[Monkey Patch] 失败: {e}")
    
    config = config
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
