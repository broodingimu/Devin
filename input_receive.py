import tkinter as tk
from tkinter import messagebox
import os
from datetime import datetime
import win32gui
import win32con
import winsound  # 用于声音报警

# 保存输入内容的文件路径
SAVE_FILE = "input_log.txt"  # 你可以修改为绝对路径来确保保存到你希望的位置
MAX_LINES = 100  # 限制最大显示的行数
MAX_DISPLAYED_BARCODES = 10  # 显示最近的10条条码

class FullScreenApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Full Screen Input")
        
        # 设置全屏
        self.root.attributes('-fullscreen', True)
        
        # 设置窗口始终在最前
        self.root.attributes("-topmost", 1)
        
        # 防止窗口被关闭
        self.root.protocol("WM_DELETE_WINDOW", self.disable_event)

        # 创建滚动条
        self.scrollbar = tk.Scrollbar(self.root)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 设置输入框，绑定滚动条
        self.text_area = tk.Text(self.root, font=("Arial", 16), wrap=tk.WORD, yscrollcommand=self.scrollbar.set)
        self.text_area.pack(expand=True, fill=tk.BOTH, side=tk.LEFT)
        self.text_area.focus_set()

        # 绑定滚动条的更新
        self.scrollbar.config(command=self.text_area.yview)
        
        # 创建右侧显示条码的框
        self.barcode_listbox = tk.Listbox(self.root, font=("Arial", 12), width=30, height=10)
        self.barcode_listbox.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        # 创建标签显示接收到的条码数量
        self.count_label = tk.Label(self.root, text="接收条码总数: 0", font=("Arial", 14))
        self.count_label.pack(side=tk.TOP, pady=10)

        # 绑定按键事件
        self.root.bind('<Return>', self.save_input)  # 保存输入
        self.root.bind('<Escape>', self.handle_escape)  # 检测两次 Esc
        self.root.bind('<Shift_L>', self.cancel_alert)  # 检测 Shift 键
        
        # 连续 Esc 检测相关
        self.escape_pressed = False
        self.escape_timer_id = None

        # 初始化第一条数据
        self.first_input = None

        # 标志是否处于报警状态
        self.alerting = False

        # 用于存储最近的条码
        self.recent_barcodes = []

        # 全局接收到条码的总数
        self.total_barcodes = 0

        # 检查窗口是否最前
        self.check_window_foreground()

    def disable_event(self):
        pass  # 禁用关闭按钮

    def save_input(self, event=None):
        """保存输入到文件，并清空界面"""
        if self.alerting:
            return "break"  # 如果处于报警状态，禁止新的输入

        input_text = self.text_area.get("1.0", tk.END).strip()
        if input_text:
            try:
                # 获取当前时间并格式化
                timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                with open(SAVE_FILE, "a", encoding="utf-8") as file:
                    file.write(f"{timestamp} {input_text}\n")
                
                # 打印日志文件保存情况（调试用）
                print(f"Saved: {timestamp} {input_text}")
                
                # 如果是第一条数据，记录下来
                if self.first_input is None:
                    self.first_input = input_text
                elif input_text != self.first_input:
                    # 如果与第一条数据不一致，弹出警告框
                    self.start_alert()

                # 清空文本框内容
                self.text_area.delete("1.0", tk.END)

                # 每次输入后，检查并限制显示行数
                self.limit_text_area_lines()

                # 更新最近的条码列表
                self.update_barcode_list(input_text)

                # 更新接收条码的总数
                self.update_barcode_count()

            except Exception as e:
                print(f"Error saving file: {e}")
        return "break"  # 禁止默认换行行为

    def handle_escape(self, event=None):
        """处理 Esc 按键逻辑"""
        if self.escape_pressed:
            self.root.destroy()  # 连续按两次 Esc 退出程序
        else:
            self.escape_pressed = True
            self.escape_timer_id = self.root.after(1000, self.reset_escape)  # 1秒后重置状态

    def reset_escape(self):
        """重置 Esc 检测状态"""
        self.escape_pressed = False
        self.escape_timer_id = None

    def cancel_alert(self, event=None):
        """按下 Shift 键取消报警并恢复状态"""
        if self.alerting:
            self.stop_alert()  # 停止报警并恢复输入框
            self.first_input = None  # 重置第一条数据
            self.text_area.config(state=tk.NORMAL)  # 重新启用输入框
            self.text_area.delete("1.0", tk.END)  # 清空输入框内容

    def start_alert(self):
        """开始报警，弹出警告框并持续播放警报声"""
        if not self.alerting:  # 只在第一次触发时报警
            self.alerting = True
            self.text_area.config(state=tk.DISABLED)  # 禁用文本框输入
            self.play_alert_sound()  # 播放报警声音
            self.show_alert_message()  # 弹出警告框
            self.change_barcode_listbox_color("red")  # 将右侧条码框背景设置为红色

    def stop_alert(self):
        """停止报警，恢复输入框状态"""
        self.alerting = False
        self.text_area.config(state=tk.NORMAL)  # 重新启用输入框
        self.change_barcode_listbox_color("white")  # 恢复右侧条码框背景色

    def play_alert_sound(self):
        """持续播放报警声音，直到 Shift 被按下"""
        if self.alerting:
            winsound.Beep(1000, 500)  # 播放警告声音
            self.root.after(500, self.play_alert_sound)  # 每隔500ms持续播放

    def show_alert_message(self):
        """弹出警告框"""
        messagebox.showwarning("警告", "输入与第一条数据不一致！请按 Shift 键恢复正常。")

    def change_barcode_listbox_color(self, color):
        """改变右侧条码显示区域的背景色"""
        self.barcode_listbox.config(bg=color)

    def check_window_foreground(self):
        """检测窗口是否在最前面，如果不在则将其抢回来"""
        def bring_to_front():
            # 获取当前窗口的句柄
            hwnd = self.root.winfo_id()
            
            # 获取窗口的当前 Z 顺序状态
            foreground_hwnd = win32gui.GetForegroundWindow()
            if hwnd != foreground_hwnd:
                # 如果窗口不在最前，将其设置为最前
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
                print("Window was not in the foreground. Brought it to front.")

            # 定时检查，确保窗口始终在最前
            self.root.after(1000, bring_to_front)  # 每秒检查一次

        bring_to_front()

    def limit_text_area_lines(self):
        """限制文本框中显示的行数，如果超过最大行数则删除最旧的内容"""
        lines = self.text_area.get("1.0", "end-1c").splitlines()
        if len(lines) > MAX_LINES:
            # 删除最早的几行，保持最大行数
            self.text_area.delete("1.0", f"{len(lines) - MAX_LINES + 1}.0")

    def update_barcode_list(self, barcode):
        """更新最近输入的条码列表，最多显示最近 10 条"""
        if len(self.recent_barcodes) >= MAX_DISPLAYED_BARCODES:
            self.recent_barcodes.pop(0)  # 删除最旧的条码

        # 将新的条码添加到列表中
        self.recent_barcodes.append(barcode)

        # 逐条添加新的条码到 Listbox，实现动态更新效果
        def update_listbox():
            self.barcode_listbox.delete(0, tk.END)  # 清空现有条目
            for i, barcode in enumerate(self.recent_barcodes[::-1]):  # 反转顺序，显示最新的条码在顶部
                self.barcode_listbox.insert(tk.END, barcode)
                self.barcode_listbox.yview(tk.END)  # 自动滚动到最底部

        self.root.after(100, update_listbox)  # 延迟执行，确保 Listbox 更新

    def update_barcode_count(self):
        """更新接收条码的总数显示"""
        self.total_barcodes += 1  # 每次输入条码时，增加计数器

        # 更新标签显示全局条码总数
        self.count_label.config(text=f"接收条码总数: {self.total_barcodes}")


# 主程序
if __name__ == "__main__":
    root = tk.Tk()
    app = FullScreenApp(root)
    root.mainloop()
