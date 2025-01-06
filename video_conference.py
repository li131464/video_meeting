import sys
import cv2
import socket
import pickle
import struct
import threading
import numpy as np
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import os
import datetime
import json
import time
import uuid
import hashlib

class VideoConference(QMainWindow):
    # 添加信号定义
    video_frame_received = pyqtSignal(np.ndarray)
    connection_status_changed = pyqtSignal(bool)
    chat_message_received = pyqtSignal(str, str)
    file_progress_updated = pyqtSignal(str, int)  # 文件名, 进度
    connection_error = pyqtSignal(str)  # 错误信息
    
    def __init__(self):
        super().__init__()
        self._init_attributes()
        self.init_ui()
        self.init_camera()
        self.setStyleSheet(self.get_style_sheet())
        self._setup_signals()

    def _init_attributes(self):
        """初始化类属性"""
        self.server = None
        self.client_socket = None
        self.is_connected = False
        self.is_host = False
        self.video_quality = 50  # 默认中等质量
        self.current_file = None
        self.clients = []
        self.retry_count = 3  # 连接重试次数
        self.chunk_size = 8192  # 文件传输块大小
        self.pending_files = {}  # 待处理的文件传输

    def _setup_signals(self):
        """设置信号连接"""
        self.video_frame_received.connect(self.update_remote_video)
        self.connection_status_changed.connect(self.update_network_status)
        self.chat_message_received.connect(self.add_chat_message)

    def get_local_ip(self):
        """获取本机局域网IP地址"""
        try:
            # 创建一个UDP套接字
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 连接一个公网IP（不需要真实连接）
            s.connect(('8.8.8.8', 80))
            # 获取本机IP
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            # 如果上述方法失败，尝试其他方法
            try:
                hostname = socket.gethostname()
                ip = socket.gethostbyname(hostname)
                return ip
            except:
                return '127.0.0.1'

    def init_ui(self):
        self.setWindowTitle('视频会议')
        self.setGeometry(100, 100, 1280, 920)
        self.create_menu_bar()

        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 控制面板（使用GroupBox包装）
        control_group = QGroupBox("会议控制")
        control_layout = QHBoxLayout()
        control_group.setLayout(control_layout)
        
        # IP和端口输入
        input_layout = QHBoxLayout()
        
        ip_widget = QWidget()
        ip_layout = QVBoxLayout(ip_widget)
        ip_label = QLabel("服务器IP地址:")
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText('例如: 192.168.1.100')
        local_ip = self.get_local_ip()  # 使用self调用方法
        self.ip_input.setText(local_ip)  # 设置默认IP为本机IP
        self.ip_input.setToolTip('创建会议时无需填写\n加入会议时输入主持人的IP地址')
        ip_layout.addWidget(ip_label)
        ip_layout.addWidget(self.ip_input)
        
        port_widget = QWidget()
        port_layout = QVBoxLayout()
        port_widget.setLayout(port_layout)
        port_label = QLabel("端口号:")
        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText('例如: 9999')
        self.port_input.setText('9999')
        self.port_input.setToolTip('请输入1024-65535之间的端口号')
        port_layout.addWidget(port_label)
        port_layout.addWidget(self.port_input)
        
        input_layout.addWidget(ip_widget)
        input_layout.addWidget(port_widget)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        
        self.create_btn = QPushButton('➕ 创建会议')
        self.create_btn.clicked.connect(self.create_meeting)
        self.create_btn.setToolTip('创建一个新的会议，其他人可以加入')
        
        self.join_btn = QPushButton('➜ 加入会议')
        self.join_btn.clicked.connect(self.join_meeting)
        self.join_btn.setToolTip('加入已有的会议')
        
        button_layout.addWidget(self.create_btn)
        button_layout.addWidget(self.join_btn)
        
        control_layout.addLayout(input_layout, stretch=2)
        control_layout.addLayout(button_layout, stretch=1)

        # 视频显示区域
        video_group = QGroupBox("视频区域")
        video_layout = QHBoxLayout()
        video_group.setLayout(video_layout)
        
        # 本地视频
        local_widget = QWidget()
        local_layout = QVBoxLayout()
        local_widget.setLayout(local_layout)
        local_label = QLabel("本地视频")
        local_label.setAlignment(Qt.AlignCenter)
        self.local_video = QLabel()
        self.local_video.setFixedSize(640, 480)
        self.local_video.setStyleSheet("border: 2px solid #cccccc; border-radius: 5px;")
        local_layout.addWidget(local_label)
        local_layout.addWidget(self.local_video)
        
        # 远程视频
        remote_widget = QWidget()
        remote_layout = QVBoxLayout()
        remote_widget.setLayout(remote_layout)
        remote_label = QLabel("远程视频")
        remote_label.setAlignment(Qt.AlignCenter)
        self.remote_video = QLabel()
        self.remote_video.setFixedSize(640, 480)
        self.remote_video.setStyleSheet("border: 2px solid #cccccc; border-radius: 5px;")
        remote_layout.addWidget(remote_label)
        remote_layout.addWidget(self.remote_video)
        
        video_layout.addWidget(local_widget)
        video_layout.addWidget(remote_widget)

        # 媒体控制区域
        controls_group = QGroupBox("媒体控制")
        controls_layout = QVBoxLayout()
        controls_group.setLayout(controls_layout)
        
        # 视频控制
        video_control_layout = QHBoxLayout()
        self.video_btn = QPushButton('📷 开启视频')
        self.video_btn.setCheckable(True)
        self.video_btn.setChecked(True)
        self.video_btn.clicked.connect(self.toggle_video)
        video_control_layout.addWidget(self.video_btn)
        
        # 视频质量控制
        quality_layout = QHBoxLayout()
        quality_label = QLabel("视频质量:")
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['低', '中', '高'])
        self.quality_combo.setCurrentText('中')
        self.quality_combo.currentTextChanged.connect(self.change_video_quality)
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.quality_combo)
        
        controls_layout.addLayout(video_control_layout)
        controls_layout.addLayout(quality_layout)

        # 创建水平分割的主布局
        main_split = QHBoxLayout()
        
        # 左侧布局（原有的视频和控制）
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_widget.setLayout(left_layout)
        
        # 添加原有的控件到左侧布局
        left_layout.addWidget(control_group)   # 会议控制
        left_layout.addWidget(video_group)     # 视频显示
        left_layout.addWidget(controls_group)  # 媒体控制
        
        # 右侧聊天和文件传输区域
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_widget.setLayout(right_layout)
        
        # 聊天区域
        chat_group = QGroupBox("聊天区域")
        chat_layout = QVBoxLayout()
        chat_group.setLayout(chat_layout)
        
        # 聊天显示区域
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setMinimumWidth(300)
        
        # 聊天输入区域
        chat_input_layout = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("输入消息...")
        self.chat_input.returnPressed.connect(self.send_chat_message)
        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self.send_chat_message)
        chat_input_layout.addWidget(self.chat_input)
        chat_input_layout.addWidget(send_btn)
        
        chat_layout.addWidget(self.chat_display)
        chat_layout.addLayout(chat_input_layout)
        
        # 文件传输区域
        file_group = QGroupBox("文件传输")
        file_layout = QVBoxLayout()
        file_group.setLayout(file_layout)
        
        # 文件列表（使用QTreeWidget来显示详细信息）
        self.file_list = QTreeWidget()
        self.file_list.setHeaderLabels(['文件名', '大小', '状态', '进度'])
        self.file_list.setColumnWidth(0, 200)  # 文件名列宽
        self.file_list.setColumnWidth(1, 80)   # 大小列宽
        self.file_list.setColumnWidth(2, 80)   # 状态列宽
        self.file_list.setColumnWidth(3, 100)  # 进度列宽
        
        # 文件传输控制
        file_control_layout = QHBoxLayout()
        self.send_file_btn = QPushButton("发送文件")
        self.send_file_btn.clicked.connect(self.send_file)
        file_control_layout.addWidget(self.send_file_btn)
        
        file_layout.addWidget(self.file_list)
        file_layout.addLayout(file_control_layout)
        
        # 添加到右侧布局
        right_layout.addWidget(chat_group)
        right_layout.addWidget(file_group)
        
        # 将左右两侧添加到主分割布局
        main_split.addWidget(left_widget, stretch=2)
        main_split.addWidget(right_widget, stretch=1)
        
        # 设置主窗口的布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_widget.setLayout(main_split)

        # 状态栏
        self.status_label = QLabel('就绪')
        self.statusBar().addWidget(self.status_label)

    def create_menu_bar(self):
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu('文件')
        
        # 查看日志选项
        view_logs_action = QAction('查看日志', self)
        view_logs_action.triggered.connect(self.show_log_viewer)
        file_menu.addAction(view_logs_action)
        
        # 退出选项
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def log_event(self, event_type, message, details=None):
        """详细的日志记录"""
        try:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            log_message = f'[{timestamp}] [{event_type}] {message}\n'
            
            if details:
                log_message += f'详细信息:\n{json.dumps(details, ensure_ascii=False, indent=2)}\n'
            
            with open('meeting_logs.txt', 'a', encoding='utf-8') as f:
                f.write(log_message)
        except Exception as e:
            print(f"写入日志失败: {e}")

    def show_log_viewer(self):
        """显示日志查看器"""
        # 先验证密码
        password, ok = QInputDialog.getText(
            self, '密码验证', '请输入密码：', 
            QLineEdit.Password
        )
        
        if ok and password == '085206':
            self.log_viewer = LogViewerDialog(self)
            self.log_viewer.show()
        else:
            QMessageBox.warning(self, '错误', '密码错误！')

    def get_style_sheet(self):
        return '''
            QMainWindow {
                background-color: #f5f5f5;
            }
            QGroupBox {
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                font-weight: bold;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 100px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:pressed {
                background-color: #0D47A1;
            }
            QPushButton:disabled {
                background-color: #BDBDBD;
            }
            QLineEdit {
                padding: 6px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                font-size: 13px;
            }
            QLabel {
                color: #333333;
                font-size: 13px;
            }
            QStatusBar {
                background-color: #E0E0E0;
            }
            QTextEdit {
                font-size: 13px;
            }
            QListWidget {
                font-size: 13px;
            }
            QComboBox {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 4px;
                font-size: 13px;
            }
            QLabel#video_label {
                background-color: #333333;
                color: white;
                border: 2px solid #cccccc;
                border-radius: 5px;
                padding: 10px;
            }
        '''

    def init_camera(self):
        """初始化摄像头"""
        self.capture = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.video_enabled = True
        self.start_camera()

    def start_camera(self):
        """启动摄像头"""
        if not self.capture:
            self.capture = cv2.VideoCapture(0)
            if not self.capture.isOpened():
                QMessageBox.warning(self, '错误', '无法打开摄像头')
                self.video_btn.setChecked(False)
                self.video_enabled = False
                return
            self.timer.start(30)  # 30ms 刷新一次，约等于 30fps
            self.video_enabled = True
            self.video_btn.setText('📷 关闭视频')

    def stop_camera(self):
        """停止摄像头"""
        if self.capture:
            self.timer.stop()
            self.capture.release()
            self.capture = None
            self.video_enabled = False
            self.video_btn.setText('📷 开启视频')
            try:
                # 安全地清空视频显示
                if hasattr(self, 'local_video') and self.local_video and not self.local_video.isHidden():
                    self.local_video.clear()
                    self.local_video.setText('视频已关闭')
            except RuntimeError:
                pass  # 忽略 Qt 对象已删除的错误

    def toggle_video(self, checked):
        """切换视频开关"""
        try:
            if checked:
                self.start_camera()
            else:
                self.stop_camera()
        except RuntimeError:
            pass  # 忽略 Qt 对象已删除的错误

    def update_frame(self):
        """优化的视频帧更新方法"""
        if not self.video_enabled or not self.capture:
            return
            
        try:
            ret, frame = self.capture.read()
            if not ret:
                return
                
            frame = self._process_video_frame(frame)
            self._display_local_video(frame)
            
            if self.is_connected:
                self._send_video_frame(frame)
                
        except Exception as e:
            self.log_event('警告', '视频帧更新失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e)
            })

    def _process_video_frame(self, frame):
        """处理视频帧"""
        frame = cv2.flip(frame, 1)  # 水平翻转
        return frame

    def _display_local_video(self, frame):
        """显示本地视频"""
        if not self.local_video or not self.local_video.isVisible():
            return
            
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        qt_image = QImage(rgb_frame.data, w, h, ch * w, QImage.Format_RGB888)
        self.local_video.setPixmap(QPixmap.fromImage(qt_image).scaled(
            self.local_video.size(), Qt.KeepAspectRatio))

    def create_meeting(self):
        """创建会议"""
        if not self.is_host and not self.is_connected:
            try:
                port = int(self.port_input.text())
                self.log_event('会议创建', '正在创建会议...', {
                    '端口': port,
                    '本机IP': self.get_local_ip(),
                    '时间': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                
                # 创建服务器套接字
                self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.server_socket.bind(('0.0.0.0', port))
                self.server_socket.listen(5)
                
                self.is_host = True
                self.is_connected = True
                self.clients = []
                
                # 启动服务器监听线程
                self.server_thread = threading.Thread(target=self.accept_connections)
                self.server_thread.daemon = True
                self.server_thread.start()
                
                # 更新界面状态
                self.status_label.setText(f'会议已创建 - 端口: {port}')
                self.create_btn.setText('结束会议')
                self.join_btn.setEnabled(False)
                self.update_network_status("connected")
                
                self.log_event('会议创建', '会议创建成功', {
                    '状态': '成功',
                    '端口': port,
                    '服务器IP': self.get_local_ip()
                })
                
            except Exception as e:
                self.log_event('错误', '创建会议失败', {
                    '错误类型': type(e).__name__,
                    '错误信息': str(e)
                })
                QMessageBox.warning(self, '错误', f'创建会议失败: {str(e)}')
                self.update_network_status("disconnected")
        else:
            self.stop_server()

    def stop_server(self):
        if self.is_host:
            for client in self.clients:
                try:
                    client.close()
                except:
                    pass
            try:
                self.server_socket.close()
            except:
                pass
            self.is_host = False
            self.is_connected = False
            self.clients = []
            self.create_btn.setText('创建会议')
            self.join_btn.setEnabled(True)
            self.status_label.setText('就绪')
            self.update_network_status("disconnected")

    def accept_connections(self):
        """接受客户端连接"""
        while self.is_host:
            try:
                client_socket, addr = self.server_socket.accept()
                
                # 立即发送连接确认消息
                try:
                    welcome_data = {
                        'type': 'system',
                        'content': 'connection_confirmed',
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    serialized_data = pickle.dumps(welcome_data)
                    size = struct.pack('!I', len(serialized_data))
                    client_socket.send(size)
                    client_socket.send(serialized_data)
                    
                    self.log_event('连接', '已发送连接确认', {
                        '客户端地址': str(addr),
                        '确认时间': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                    
                    # 添加到客户端列表
                    self.clients.append(client_socket)
                    
                    # 启动新线程处理客户端连接
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except Exception as e:
                    self.log_event('错误', '发送连接确认失败', {
                        '错误类型': type(e).__name__,
                        '错误信息': str(e),
                        '客户端地址': str(addr)
                    })
                    try:
                        client_socket.close()
                    except:
                        pass
                
            except Exception as e:
                if self.is_host:  # 只在非正常关闭时记录错误
                    self.log_event('错误', '接受客户端连接失败', {
                        '错误类型': type(e).__name__,
                        '错误信息': str(e)
                    })

    def handle_client(self, client_socket, addr):
        """处理客户端连接"""
        try:
            self.log_event('连接', f'开始处理客户端连接: {addr}', {
                '连接时间': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '客户端地址': str(addr)
            })
            
            while self.is_host:
                try:
                    # 接收数据大小
                    size_data = client_socket.recv(struct.calcsize('!I'))
                    if not size_data:
                        self.log_event('连接', '客户端断开连接(size_data为空)', {
                            '客户端地址': str(addr)
                        })
                        break
                        
                    data_size = struct.unpack('!I', size_data)[0]
                    
                    # 接收完整数据
                    received_data = b""
                    while len(received_data) < data_size:
                        chunk = client_socket.recv(min(data_size - len(received_data), 8192))
                        if not chunk:
                            self.log_event('连接', '客户端断开连接(接收数据中断)', {
                                '客户端地址': str(addr)
                            })
                            break
                        received_data += chunk
                    
                    if not received_data:
                        break
                        
                    # 处理接收到的数据
                    try:
                        data = pickle.loads(received_data)
                        
                        self.log_event('数据接收', '收到客户端数据', {
                            '数据类型': data.get('type'),
                            '数据内容': str(data),
                            '客户端地址': str(addr)
                        })
                        
                        # 在主线程中处理数据
                        if data['type'] == 'chat':
                            QMetaObject.invokeMethod(
                                self,
                                'add_chat_message',
                                Qt.QueuedConnection,
                                Q_ARG(str, "对方" if data.get('sender') == 'client' else "主持人"),
                                Q_ARG(str, data['content'])
                            )
                        elif data['type'] == 'video':
                            # 处理视频数据
                            pass
                        elif data['type'] == 'file':
                            # 处理文件数据
                            pass
                            
                    except Exception as e:
                        self.log_event('错误', '数据处理失败', {
                            '错误类型': type(e).__name__,
                            '错误信息': str(e),
                            '数据大小': len(received_data),
                            '原始数据': str(received_data[:100]) + '...' if len(received_data) > 100 else str(received_data)
                        })
                        continue
                        
                except Exception as e:
                    self.log_event('错误', '处理客户端数据时出错', {
                        '错误类型': type(e).__name__,
                        '错误信息': str(e),
                        '客户端地址': str(addr)
                    })
                    break
                
        finally:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            try:
                client_socket.close()
            except:
                pass
            self.log_event('连接', f'客户端连接处理结束: {addr}')

    def send_to_client(self, client_socket, data):
        """发送数据到指定客户端"""
        try:
            serialized_data = pickle.dumps(data)
            size = struct.pack('!I', len(serialized_data))
            client_socket.send(size)
            client_socket.send(serialized_data)
        except Exception as e:
            self.log_event('错误', '发送数据到客户端失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e)
            })
            raise

    def receive_from_client(self, client_socket):
        """从客户端接收数据"""
        # 接收数据大小
        size_data = client_socket.recv(struct.calcsize('!I'))
        if not size_data:
            return None
        
        data_size = struct.unpack('!I', size_data)[0]
        
        # 接收完整数据
        received_data = b""
        while len(received_data) < data_size:
            chunk = client_socket.recv(min(data_size - len(received_data), 8192))
            if not chunk:
                return None
            received_data += chunk
        
        return pickle.loads(received_data)

    def broadcast_data(self, data, exclude_socket=None):
        """广播数据给所有客户端"""
        try:
            # 序列化数据
            serialized_data = pickle.dumps(data)
            size = struct.pack('!I', len(serialized_data))
            
            # 发送给所有客户端（除了指定排除的socket）
            for client in self.clients[:]:  # 使用切片创建副本以避免迭代时修改
                if client != exclude_socket:
                    try:
                        client.send(size)
                        client.send(serialized_data)
                    except Exception as e:
                        self.log_event('错误', '向客户端发送数据失败', {
                            '错误类型': type(e).__name__,
                            '错误信息': str(e)
                        })
                        # 如果发送失败，移除该客户端
                        if client in self.clients:
                            self.clients.remove(client)
                            try:
                                client.close()
                            except:
                                pass
            
            # 在服务端显示消息（如果是聊天消息）
            if data['type'] == 'chat':
                QMetaObject.invokeMethod(
                    self, 
                    'add_chat_message',
                    Qt.QueuedConnection,
                    Q_ARG(str, "对方" if data.get('sender') == 'client' else "我"),
                    Q_ARG(str, data['content'])
                )
                
        except Exception as e:
            self.log_event('错误', '广播数据失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e)
            })

    def receive_data(self):
        """接收数据（客户端模式）"""
        try:
            while self.is_connected and not self.is_host:
                # 接收数据大小
                size_data = self.client_socket.recv(struct.calcsize('!I'))
                if not size_data:
                    break
                
                data_size = struct.unpack('!I', size_data)[0]
                
                # 接收完整数据
                received_data = b""
                while len(received_data) < data_size:
                    chunk = self.client_socket.recv(min(data_size - len(received_data), 8192))
                    if not chunk:
                        break
                    received_data += chunk
                
                if not received_data:
                    break
                
                # 处理接收到的数据
                data = pickle.loads(received_data)
                self.handle_received_data(data)
                
        except Exception as e:
            print(f"接收数据时出错: {e}")
        finally:
            self.disconnect_from_meeting()

    def join_meeting(self):
        """优化的会议加入方法"""
        if not self.is_connected:
            ip = self.ip_input.text()
            port = int(self.port_input.text())
            
            for attempt in range(self.retry_count):
                try:
                    self._connect_to_server(ip, port)
                    break
                except Exception as e:
                    if attempt == self.retry_count - 1:
                        self.connection_error.emit(f"连接失败: {str(e)}")
                        return
                    time.sleep(1)  # 重试前等待
        else:
            self.disconnect_from_meeting()

    def _connect_to_server(self, ip, port):
        """建立服务器连接"""
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.settimeout(5)
        self.client_socket.connect((ip, port))
        
        # 等待连接确认
        if self._wait_for_connection_confirm():
            self._setup_client_connection()
        else:
            raise Exception("未收到服务器确认")

    def _wait_for_connection_confirm(self):
        """等待服务器确认连接"""
        try:
            data = self._receive_data()
            if data and data.get('type') == 'system' and data.get('content') == 'connection_confirmed':
                return True
            return False
        except Exception:
            return False

    def _setup_client_connection(self):
        """设置客户端连接"""
        self.client_socket.settimeout(None)
        self.is_connected = True
        self._start_receive_thread()
        self._update_ui_after_connect()

    def disconnect_from_meeting(self):
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        self.is_connected = False
        self.join_btn.setText('加入会议')
        self.create_btn.setEnabled(True)
        self.status_label.setText('就绪')
        self.update_network_status("disconnected")
        self.add_chat_message("系统", "已断开连接")

    def receive_video(self):
        while self.is_connected:
            try:
                # 接收数据大小信息
                data_size = struct.unpack('L', self.client_socket.recv(struct.calcsize('L')))[0]
                
                # 接收视频数据
                received_data = b""
                while len(received_data) < data_size:
                    data = self.client_socket.recv(min(data_size - len(received_data), 4096))
                    received_data += data

                # 解码并显示远程视频
                frame = cv2.imdecode(
                    np.frombuffer(received_data, dtype=np.uint8), 
                    cv2.IMREAD_COLOR
                )
                if frame is not None:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_frame.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    self.remote_video.setPixmap(QPixmap.fromImage(qt_image).scaled(
                        self.remote_video.size(), Qt.KeepAspectRatio))
            except Exception as e:
                self.disconnect_from_meeting()
                break

    def closeEvent(self, event):
        """关闭程序时的处理"""
        try:
            # 先停止定时器
            if hasattr(self, 'timer'):
                self.timer.stop()
            
            # 释放摄像头
            if hasattr(self, 'capture') and self.capture is not None:
                self.capture.release()
                self.capture = None
            
            # 关闭网络连接
            if self.is_host:
                self.stop_server()
            if self.is_connected:
                self.disconnect_from_meeting()
        except:
            pass  # 忽略关闭时的错误
        
        # 接受关闭事件
        event.accept()

    def update_network_status(self, status):
        """更新网络状态指示器"""
        try:
            if status == "connected":
                self.network_indicator.setStyleSheet(
                    "background-color: #4CAF50; border-radius: 8px;"
                )
                self.network_status.setText("已连接")
            elif status == "connecting":
                self.network_indicator.setStyleSheet(
                    "background-color: #FFC107; border-radius: 8px;"
                )
                self.network_status.setText("连接中...")
            else:  # disconnected
                self.network_indicator.setStyleSheet(
                    "background-color: #F44336; border-radius: 8px;"
                )
                self.network_status.setText("未连接")
        except:
            pass  # 防止在关闭程序时出现错误

    def change_video_quality(self, quality):
        """更改视频质量"""
        quality_settings = {
            '低': 30,
            '中': 50,
            '高': 80
        }
        self.video_quality = quality_settings[quality]
        self.status_label.setText(f'视频质量已设置为: {quality}')

    def change_volume(self, value):
        """更改音量"""
        if not self.mute_btn.isChecked():
            self.status_label.setText(f'音量: {value}%')
            # TODO: 实现音频控制

    def toggle_mute(self, checked):
        """静音切换"""
        if checked:
            self.mute_btn.setIcon(QIcon("icons/mute.png"))
            self.volume_slider.setEnabled(False)
            self.status_label.setText('已静音')
        else:
            self.mute_btn.setIcon(QIcon("icons/volume.png"))
            self.volume_slider.setEnabled(True)
            self.status_label.setText('已取消静音')

    def send_chat_message(self):
        """发送聊天消息"""
        message = self.chat_input.text().strip()
        if message and self.is_connected:
            try:
                data = {
                    'type': 'chat',
                    'content': message,
                    'timestamp': QDateTime.currentDateTime().toString('HH:mm:ss'),
                    'sender': 'host' if self.is_host else 'client'
                }
                
                if self.is_host:
                    # 如果是主持人，直接广播
                    self.broadcast_data(data)
                    # 在本地显示消息
                    self.add_chat_message("我", message)
                else:
                    # 如果是客户端，发送给服务器
                    self.send_data(data)
                    # 在本地显示消息
                    self.add_chat_message("我", message)
                
                self.chat_input.clear()
                
            except Exception as e:
                self.log_event('错误', '发送消息失败', {
                    '错误类型': type(e).__name__,
                    '错误信息': str(e)
                })

    def send_file(self):
        """优化的文件发送方法"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if not file_path:
            return
            
        try:
            file_info = self._prepare_file_info(file_path)
            if not file_info:
                return
                
            # 创建传输任务
            transfer_id = str(uuid.uuid4())
            self.pending_files[transfer_id] = {
                'path': file_path,
                'info': file_info,
                'status': 'preparing'
            }
            
            # 启动传输线程
            transfer_thread = threading.Thread(
                target=self._file_transfer_task,
                args=(transfer_id,)
            )
            transfer_thread.daemon = True
            transfer_thread.start()
            
        except Exception as e:
            self.log_event('错误', '准备文件传输失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e),
                '文件路径': file_path
            })

    def _prepare_file_info(self, file_path):
        """准备文件信息"""
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            return {
                'name': file_name,
                'size': file_size,
                'md5': self._calculate_file_md5(file_path)
            }
        except Exception as e:
            self.log_event('错误', '获取文件信息失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e)
            })
            return None

    def _calculate_file_md5(self, file_path):
        """计算文件MD5"""
        md5_hash = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()

    def _file_transfer_task(self, transfer_id):
        """文件传输任务"""
        file_info = self.pending_files[transfer_id]
        try:
            # 发送文件信息
            self.send_data({
                'type': 'file_info',
                'transfer_id': transfer_id,
                'info': file_info['info']
            })
            
            # 分块发送文件
            sent_size = 0
            file_size = file_info['info']['size']
            
            with open(file_info['path'], 'rb') as f:
                while sent_size < file_size:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        break
                        
                    self.send_data({
                        'type': 'file_data',
                        'transfer_id': transfer_id,
                        'chunk': chunk
                    })
                    
                    sent_size += len(chunk)
                    progress = int(sent_size * 100 / file_size)
                    self.file_progress_updated.emit(file_info['info']['name'], progress)
            
            # 发送传输完成消息
            self.send_data({
                'type': 'file_end',
                'transfer_id': transfer_id,
                'md5': file_info['info']['md5']
            })
            
        except Exception as e:
            self.log_event('错误', '文件传输失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e),
                '传输ID': transfer_id
            })
        finally:
            del self.pending_files[transfer_id]

    def _handle_file_data(self, data):
        """处理文件数据"""
        transfer_id = data.get('transfer_id')
        if not transfer_id in self.pending_files:
            return
            
        try:
            file_info = self.pending_files[transfer_id]
            if data['type'] == 'file_data':
                file_info['buffer'].extend(data['chunk'])
                progress = int(len(file_info['buffer']) * 100 / file_info['size'])
                self.file_progress_updated.emit(file_info['info']['name'], progress)
                
            elif data['type'] == 'file_end':
                self._complete_file_transfer(transfer_id)
                
        except Exception as e:
            self.log_event('错误', '处理文件数据失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e),
                '传输ID': transfer_id
            })

    def _complete_file_transfer(self, transfer_id):
        """完成文件传输"""
        file_info = self.pending_files[transfer_id]
        
        # 验证文件完整性
        received_md5 = hashlib.md5(file_info['buffer']).hexdigest()
        if received_md5 != file_info['info']['md5']:
            raise Exception("文件校验失败")
            
        # 保存文件
        file_path, ok = QFileDialog.getSaveFileName(
            self,
            "保存文件",
            file_info['info']['name']
        )
        
        if ok and file_path:
            with open(file_path, 'wb') as f:
                f.write(file_info['buffer'])
            self.file_progress_updated.emit(file_info['info']['name'], 100)
            
        del self.pending_files[transfer_id]

    def format_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"

    def add_chat_message(self, sender, message):
        """添加聊天消息到显示区域"""
        timestamp = QDateTime.currentDateTime().toString('HH:mm:ss')
        self.chat_display.append(f'[{timestamp}] {sender}: {message}')

    def add_participant(self, name):
        """添加参会者"""
        self.participants_list.addItem(name)
        self.add_chat_message("系统", f"{name} 加入了会议")

    def remove_participant(self, name):
        """移除参会者"""
        items = self.participants_list.findItems(name, Qt.MatchExactly)
        for item in items:
            self.participants_list.takeItem(self.participants_list.row(item))
        self.add_chat_message("系统", f"{name} 离开了会议")

    def update_file_progress(self, filename, progress):
        """更新文件传输进度"""
        self.status_label.setText(f'文件传输中: {filename} ({progress}%)')

    def handle_remote_video(self, frame):
        # 处理视频数据
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        self.remote_video.setPixmap(QPixmap.fromImage(qt_image).scaled(
            self.remote_video.size(), Qt.KeepAspectRatio))

    def update_remote_video(self, frame_data):
        """更新远程视频显示"""
        try:
            # 解码视频帧
            nparr = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            # 转换为Qt图像
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            # 在远程视频标签上显示
            if self.remote_video and self.remote_video.isVisible():
                self.remote_video.setPixmap(QPixmap.fromImage(qt_image).scaled(
                    self.remote_video.size(), Qt.KeepAspectRatio))
        except Exception as e:
            self.log_event('错误', '更新远程视频失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e)
            })

    def send_video_data(self, data):
        """发送视频数据到服务端"""
        try:
            data_size = struct.pack('L', len(data))
            self.client_socket.send(data_size)
            self.client_socket.send(data)
        except Exception as e:
            # 不记录视频相关的错误日志
            pass

    def _handle_chat_data(self, data):
        """处理接收到的聊天消息"""
        try:
            sender = "对方" if data.get('sender') == 'client' else "主持人"
            message = data.get('content', '')
            self.add_chat_message(sender, message)
        except Exception as e:
            self.log_event('错误', '处理聊天消息失败', {
                '错误类型': type(e).__name__,
                '错误信息': str(e)
            })

class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('会议日志查看器')
        self.setGeometry(100, 100, 800, 600)
        
        layout = QVBoxLayout()
        
        # 工具栏
        toolbar_layout = QHBoxLayout()
        
        # 刷新按钮
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.load_logs)
        toolbar_layout.addWidget(refresh_btn)
        
        # 导出按钮
        export_btn = QPushButton('导出')
        export_btn.clicked.connect(self.export_logs)
        toolbar_layout.addWidget(export_btn)
        
        # 搜索框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('搜索...')
        self.search_input.textChanged.connect(self.filter_logs)
        toolbar_layout.addWidget(self.search_input)
        
        # 日期筛选
        self.date_filter = QDateEdit()
        self.date_filter.setDate(QDate.currentDate())
        self.date_filter.dateChanged.connect(self.filter_logs)
        toolbar_layout.addWidget(self.date_filter)
        
        layout.addLayout(toolbar_layout)
        
        # 日志显示区域
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        layout.addWidget(self.log_display)
        
        # 状态栏
        self.status_label = QLabel('就绪')
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
        # 加载日志
        self.load_logs()
        
    def load_logs(self):
        try:
            log_file = 'meeting_logs.txt'
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    self.full_logs = f.readlines()
                self.filter_logs()
                self.status_label.setText(f'已加载 {len(self.full_logs)} 条日志记录')
            else:
                self.status_label.setText('日志文件不存在')
        except Exception as e:
            QMessageBox.warning(self, '错误', f'加载日志失败: {str(e)}')
            
    def filter_logs(self):
        if not hasattr(self, 'full_logs'):
            return
            
        search_text = self.search_input.text().lower()
        selected_date = self.date_filter.date().toString('yyyy-MM-dd')
        
        filtered_logs = []
        for log in self.full_logs:
            if search_text in log.lower() and selected_date in log:
                filtered_logs.append(log)
                
        self.log_display.setText(''.join(filtered_logs))
        self.status_label.setText(f'显示 {len(filtered_logs)} 条记录')
        
    def export_logs(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出日志",
            f"meeting_logs_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_display.toPlainText())
                QMessageBox.information(self, '成功', '日志导出成功！')
            except Exception as e:
                QMessageBox.warning(self, '错误', f'导出日志失败: {str(e)}')

if __name__ == '__main__':
    app = QApplication(sys.argv)
    conference = VideoConference()
    conference.show()
    sys.exit(app.exec_())