#!/usr/bin/env python3
"""独立测试 overlay 是否能在屏幕上显示"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import time
import logging
logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(name)s: %(message)s')

import AppKit
from PyObjCTools import AppHelper

def test_overlay():
    """在屏幕中央创建一个半透明黑色面板，持续 5 秒"""
    # 获取屏幕尺寸
    screen = AppKit.NSScreen.mainScreen()
    screen_frame = screen.frame()
    sw, sh = screen_frame.size.width, screen_frame.size.height
    
    # 在屏幕中央创建 400x300 的覆盖层
    x, y, w, h = (sw - 400) / 2, (sh - 300) / 2, 400, 300
    rect = ((x, y), (w, h))
    
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect,
        AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
        AppKit.NSBackingStoreBuffered,
        False
    )
    panel.setBackgroundColor_(AppKit.NSColor.blackColor())
    panel.setIgnoresMouseEvents_(True)
    panel.setLevel_(AppKit.NSFloatingWindowLevel)
    panel.setOpaque_(False)
    panel.setHasShadow_(False)
    panel.setAlphaValue_(0.5)  # 50% 不透明度 - 应该明显可见
    panel.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
        AppKit.NSWindowCollectionBehaviorTransient
    )
    panel.orderFrontRegardless()
    
    print(f"✓ Overlay panel created at ({x}, {y}, {w}, {h}) with alpha=0.5")
    print(f"  Panel visible: {panel.isVisible()}")
    print(f"  Panel frame: {panel.frame()}")
    print("  You should see a semi-transparent black rectangle in the center of your screen.")
    print("  It will disappear in 5 seconds...")
    
    # 5 秒后关闭
    def close_after_delay():
        time.sleep(5)
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: panel.orderOut_(None)
        )
        print("✓ Overlay removed")
        AppKit.NSApp.terminate_(None)
    
    import threading
    threading.Thread(target=close_after_delay, daemon=True).start()

# 创建 NSApplication 并运行
app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

# 延迟执行测试
AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(test_overlay)

print("Starting NSApplication event loop...")
AppHelper.runEventLoop()
