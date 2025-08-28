import time
import requests
from datetime import datetime, timezone, timedelta
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QThread
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QWidget, QVBoxLayout, QScrollBar
from loguru import logger
from qfluentwidgets import isDarkTheme

WIDGET_CODE = 'widget_voicehub.ui'
WIDGET_NAME = '广播站排期 | LaoShui'
WIDGET_WIDTH = 380
API_URL = "https://voicehub.lao-shui.top/api/songs/public"

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/91.0.4472.124 Safari/537.36 Edge/91.0.864.64'
    )
}


class FetchThread(QThread):
    """网络请求线程"""
    fetch_finished = pyqtSignal(list, object)  # 成功信号，传递歌曲列表和日期
    fetch_failed = pyqtSignal()  # 失败信号

    def __init__(self):
        super().__init__()
        self.max_retries = 3

    def run(self):
        retry_count = 0
        while retry_count < self.max_retries:
            try:
                response = requests.get(API_URL, headers=HEADERS, proxies={'http': None, 'https': None})
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list) and data:
                    # 获取今天的日期
                    today = datetime.now(timezone(timedelta(hours=8))).date()  # 使用北京时间

                    # 先尝试获取今天的歌曲
                    today_songs = []
                    for item in data:
                        play_date = datetime.fromisoformat(item['playDate'].replace('Z', '+00:00')).date()
                        if play_date == today:
                            today_songs.append(item)

                    # 按sequence排序
                    today_songs.sort(key=lambda x: x.get('sequence', 0))

                    if today_songs:
                        self.fetch_finished.emit(today_songs, today)
                        return
                    else:
                        logger.warning("今天没有找到歌曲排期，尝试查找往后最近的排期")

                        # 如果今天没有排期，查找往后最近的排期
                        future_dates = {}
                        for item in data:
                            play_date = datetime.fromisoformat(item['playDate'].replace('Z', '+00:00')).date()
                            if play_date > today:  # 只查找今天之后的日期
                                if play_date not in future_dates:
                                    future_dates[play_date] = []
                                future_dates[play_date].append(item)

                        if future_dates:
                            # 找到最近的日期
                            nearest_date = min(future_dates.keys())
                            nearest_songs = future_dates[nearest_date]
                            nearest_songs.sort(key=lambda x: x.get('sequence', 0))

                            logger.info(f"找到往后最近的排期日期: {nearest_date}")
                            self.fetch_finished.emit(nearest_songs, nearest_date)
                            return
                        else:
                            logger.warning("未找到任何往后的排期")

            except Exception as e:
                logger.error(f"请求失败: {e}")

            retry_count += 1
            time.sleep(2)

        self.fetch_failed.emit()


class SmoothScrollBar(QScrollBar):
    """平滑滚动条"""
    scrollFinished = pyqtSignal()

    def __init__(self, parent=None):
        QScrollBar.__init__(self, parent)
        self.ani = QPropertyAnimation()
        self.ani.setTargetObject(self)
        self.ani.setPropertyName(b"value")
        self.ani.setEasingCurve(QEasingCurve.OutCubic)
        self.ani.setDuration(400)
        self.__value = self.value()
        self.ani.finished.connect(self.scrollFinished)

    def setValue(self, value: int):
        if value == self.value():
            return

        self.ani.stop()
        self.scrollFinished.emit()

        self.ani.setStartValue(self.value())
        self.ani.setEndValue(value)
        self.ani.start()

    def wheelEvent(self, e):
        e.ignore()

    def scrollValue(self, delta):
        """滚动一定值"""
        new_value = self.value() - delta / 120 * 40
        new_value = max(0, min(new_value, self.maximum()))
        self.setValue(int(new_value))


class SmoothScrollArea(QScrollArea):
    """平滑滚动区域"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vScrollBar = SmoothScrollBar()
        self.setVerticalScrollBar(self.vScrollBar)
        self.setStyleSheet("QScrollBar:vertical { width: 0px; }")
        self.content_widget = None
        self.songs = []
        self.font_color = "#000000"
        self.current_song_index = 0

    def wheelEvent(self, e):
        if hasattr(self.vScrollBar, 'scrollValue'):
            self.vScrollBar.scrollValue(-e.angleDelta().y())

    def set_songs(self, songs, font_color="#000000", display_date=None):
        """设置歌曲列表并显示"""
        self.songs = songs
        self.font_color = font_color
        self.current_song_index = 0

        # 初始化内容widget
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(15)

        # 创建歌曲容器
        if songs:
            songs_container = self.create_songs_container(songs)
            content_layout.addWidget(songs_container)
        else:
            # 如果没有歌曲，显示提示
            no_songs_label = QLabel("暂无歌曲排期")
            no_songs_label.setAlignment(Qt.AlignCenter)
            no_songs_label.setStyleSheet(f"""
                font-size: 14px;
                color: {self.font_color};
                padding: 20px;
                background: none;
            """)
            content_layout.addWidget(no_songs_label)

        # 只在正常状态时添加版权信息（非加载、非错误状态）
        if songs and len(songs) > 0:
            first_song = songs[0].get('song', {})
            title = first_song.get('title', '')
            # 排除加载和错误状态
            if title not in ['正在加载中...', '网络连接异常']:
                copyright_label = QLabel("Supported by VoiceHub | LaoShui @ 2025")
                copyright_label.setAlignment(Qt.AlignCenter)
                copyright_label.setStyleSheet(f"""
                    font-size: 14px;
                    color: {self.font_color};
                    padding: 10px 5px 5px 5px;
                    background: none;
                    opacity: 0.7;
                """)
                content_layout.addWidget(copyright_label)

        # 设置滚动区域的widget
        self.setWidget(self.content_widget)

    def create_songs_container(self, songs):
        """创建歌曲容器"""
        container = QWidget()
        container.setObjectName("songsContainer")  # 设置特定的对象名称
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(15, 0, 0, 0)  # 直接设置左边距
        container_layout.setSpacing(0)

        # 设置容器样式 - 使用特定选择器，只有左侧蓝色边框
        container.setStyleSheet("""
            QWidget#songsContainer {
                background: transparent;
                border-left: 4px solid #007ACC;
            }
        """)

        # 添加所有歌曲
        for i, song_item in enumerate(songs, 1):
            song_label = self.create_song_label(song_item, i)
            container_layout.addWidget(song_label)

        return container

    def create_song_label(self, song_item, sequence):
        """创建单首歌曲标签"""
        song = song_item.get('song', {})

        # 获取歌曲信息
        artist = song.get('artist', '未知艺术家')
        title = song.get('title', '未知歌曲')
        requester = song.get('requester', '未知')
        vote_count = song.get('voteCount', 0)

        # 创建简洁的单行显示
        song_text = f"{sequence}. {artist} - {title} - {requester} - 热度:{vote_count}"

        song_label = QLabel(song_text)
        song_label.setAlignment(Qt.AlignLeft)
        song_label.setWordWrap(True)
        song_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: bold;
            color: {self.font_color};
            padding: 4px 0;
            margin: 0;
            background: transparent;
            border: none;
        """)

        return song_label


class Plugin:
    def __init__(self, cw_contexts, method):
        self.cw_contexts = cw_contexts
        self.method = method

        self.CONFIG_PATH = f'{cw_contexts["PLUGIN_PATH"]}/config.json'
        self.PATH = cw_contexts['PLUGIN_PATH']

        self.method.register_widget(WIDGET_CODE, WIDGET_NAME, WIDGET_WIDTH)

        self.scroll_position = 0
        self.enable_scrolling = False
        self.timer = QTimer()
        self.timer.timeout.connect(self.auto_scroll)
        self.timer.start(100)  # 滚动速度

        # 定时器用于延迟重试
        self.retry_timer = QTimer()
        self.retry_timer.timeout.connect(self.update_songs)

        # 定时器用于定期更新（每30分钟）
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_songs)
        self.update_timer.start(30 * 60 * 1000)  # 30分钟

        # 初始显示加载状态
        self.show_loading()

    def show_loading(self):
        """显示加载状态"""
        self.enable_scrolling = False
        self.update_widget_content([], loading=True)

    def update_songs(self):
        """启动异步更新歌曲排期"""
        self.show_loading()
        self.retry_timer.stop()

        self.worker_thread = FetchThread()
        self.worker_thread.fetch_finished.connect(self.handle_success)
        self.worker_thread.fetch_failed.connect(self.handle_failure)
        self.worker_thread.start()

    def handle_success(self, songs, display_date):
        """处理成功响应"""
        self.enable_scrolling = True
        self.update_widget_content(songs, display_date=display_date)
        logger.success(f"成功获取到 {len(songs)} 首歌曲的排期信息")

    def handle_failure(self):
        """处理失败情况"""
        logger.warning("重试3次失败，5分钟后自动重试")
        self.enable_scrolling = False
        self.update_widget_content([], error=True)
        self.retry_timer.start(5 * 60 * 1000)  # 5分钟重试

    def update_widget_content(self, songs, loading=False, error=False, display_date=None):
        """更新小组件内容（线程安全）"""
        self.test_widget = self.method.get_widget(WIDGET_CODE)
        if not self.test_widget:
            logger.error(f"小组件未找到，WIDGET_CODE: {WIDGET_CODE}")
            return

        # 使用QTimer.singleShot确保在主线程执行UI操作
        QTimer.singleShot(0, lambda: self._update_ui(songs, loading, error, display_date))

    def _update_ui(self, songs, loading=False, error=False, display_date=None):
        """实际执行UI更新的方法"""
        content_layout = self.find_child_layout(self.test_widget, 'contentLayout')
        if not content_layout:
            logger.error("未能找到小组件的'contentLayout'布局")
            return

        content_layout.setSpacing(5)

        # 动态更新小组件标题
        if display_date:
            widget_title = f"广播站排期 | {display_date.strftime('%Y/%m/%d')}"
        else:
            widget_title = "广播站排期 | LaoShui"

        self.method.change_widget_content(WIDGET_CODE, widget_title, widget_title)

        # 清除旧内容
        self.clear_existing_content(content_layout)

        # 创建滚动区域并设置内容
        scroll_area = self.create_scroll_area(songs, loading, error, display_date)
        if scroll_area:
            content_layout.addWidget(scroll_area)
            if not loading and not error:
                logger.success('广播站排期内容更新成功！')
        else:
            logger.error("滚动区域创建失败")

    @staticmethod
    def find_child_layout(widget, layout_name):
        """根据名称查找并返回布局"""
        return widget.findChild(QHBoxLayout, layout_name)

    def create_scroll_area(self, songs, loading=False, error=False, display_date=None):
        scroll_area = SmoothScrollArea()
        scroll_area.setWidgetResizable(True)

        if isDarkTheme():
            font_color = "#FFFFFF"  # 白色字体
        else:
            font_color = "#000000"  # 黑色字体

        if loading:
            # 显示加载状态
            loading_songs = [{
                'sequence': 1,
                'played': False,
                'song': {
                    'title': '正在加载中...',
                    'artist': 'LaoShui',
                    'requester': '系统'
                }
            }]
            scroll_area.set_songs(loading_songs, font_color, display_date)
        elif error:
            # 显示错误状态
            error_songs = [{
                'sequence': 1,
                'played': False,
                'song': {
                    'title': '网络连接异常',
                    'artist': '5分钟后自动重试',
                    'requester': 'LaoShui'
                }
            }]
            scroll_area.set_songs(error_songs, font_color, display_date)
        else:
            # 显示正常歌曲列表
            scroll_area.set_songs(songs, font_color, display_date)

        return scroll_area

    @staticmethod
    def clear_existing_content(content_layout):
        """清除布局中的旧内容"""
        while content_layout.count() > 0:
            item = content_layout.takeAt(0)
            if item:
                child_widget = item.widget()
                if child_widget:
                    child_widget.deleteLater()

    def auto_scroll(self):
        """自动滚动功能"""
        if not self.test_widget or not self.enable_scrolling:
            return

        # 查找 SmoothScrollArea
        scroll_area = self.test_widget.findChild(SmoothScrollArea)
        if not scroll_area:
            return

        # 查找滚动条
        vertical_scrollbar = scroll_area.verticalScrollBar()
        if not vertical_scrollbar:
            return

        # 执行滚动逻辑
        max_value = vertical_scrollbar.maximum()
        if 0 < max_value <= self.scroll_position:
            self.scroll_position = 0  # 滚动回顶部
        elif max_value == 0:
            self.scroll_position = 0
        else:
            self.scroll_position += 1  # 向下滚动

        vertical_scrollbar.setValue(self.scroll_position)

    def execute(self):
        """首次执行"""
        self.update_songs()