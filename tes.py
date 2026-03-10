import sys, os, json, time, random
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QThread, pyqtSignal

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

COOKIE_FILE = "cookies.json"
GROUP_FILE = "groups.txt"

# ===================== STEALTH + HUMAN =====================
def human_delay(a=2, b=5):
    time.sleep(random.uniform(a, b))

# ===================== TEXT SANITIZE =====================
def sanitize_text(text):
    return ''.join(c for c in text if ord(c) <= 0xFFFF)

# ===================== COOKIE =====================
def load_cookies(driver):
    if not os.path.exists(COOKIE_FILE):
        return False
    cookies = json.load(open(COOKIE_FILE, encoding="utf-8"))
    for c in cookies:
        try:
            driver.add_cookie({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".facebook.com"),
                "path": c.get("path", "/")
            })
        except:
            pass
    return True

# ===================== SAVE / LOAD GROUP =====================
def save_groups(groups):
    with open(GROUP_FILE, "w", encoding="utf-8") as f:
        for g in groups:
            f.write(g + "\n")

def load_groups():
    if not os.path.exists(GROUP_FILE):
        return []
    return [l.strip() for l in open(GROUP_FILE, encoding="utf-8") if l.strip()]

# ===================== FETCH GROUP AUTO SCROLL =====================
def fetch_groups_scroll(driver, max_groups=50, log_func=print):
    driver.get("https://web.facebook.com/groups/joins/?nav_source=tab")
    human_delay(5, 7)

    groups = set()
    last = 0

    while len(groups) < max_groups:
        links = driver.find_elements(By.XPATH, "//a[contains(@href,'/groups/')]")
        for a in links:
            h = a.get_attribute("href")
            if not h:
                continue

            clean = h.split("?")[0].rstrip("/")

            if (
                "/groups/" in clean
                and clean.count("/") >= 4
                and not clean.endswith(("/feed", "/discover", "/joins", "/groups", "/members", "/about", "/pending"))
                and clean.split("/groups/")[-1].strip()
            ):
                groups.add(clean)

        log_func(f"🔄 Total group sementara: {len(groups)}")

        if len(groups) == last:
            break
        last = len(groups)

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_delay(3, 5)

    return list(groups)[:max_groups]

# ===================== POSTING LOGIC (ASLI) =====================
def open_group_composer(driver):
    triggers = driver.find_elements(By.XPATH,
        "//div[@role='button']//span[normalize-space()='Tulis sesuatu...'] | "
        "//span[normalize-space()='Tulis sesuatu...']"
    )
    if triggers:
        driver.execute_script("arguments[0].click();", triggers[0])
        return True
    return False

def wait_group_editor(driver, timeout=15):
    try:
        editor = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//div[@role='textbox' and @contenteditable='true' "
                "and @data-lexical-editor='true' "
                "and contains(@aria-placeholder,'posting')]"
            ))
        )
        return editor
    except:
        return None

def input_text_strict(driver, element, text):
    clean = sanitize_text(text)
    try:
        driver.execute_script("arguments[0].click();", element)
        time.sleep(0.8)

        ActionChains(driver).move_to_element(element).click().send_keys(clean).perform()
        time.sleep(1)

        if not element.text.strip():
            driver.execute_script("""
                arguments[0].innerHTML = arguments[1];
                arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
            """, element, clean)
            time.sleep(1)

        return True
    except:
        return False

def wait_post_button(driver, timeout=15):
    try:
        btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((
                By.XPATH,
                "//div[@role='button' and @aria-label='Posting']"
            ))
        )
        return btn
    except:
        return None

# ===================== FUNGSI BARU: ATTACH MEDIA =====================
def attach_media(driver, image_path, log_func=print, timeout=30):
    if not image_path or not os.path.exists(image_path):
        log_func("   ⚠️ File media tidak ditemukan")
        return False

    abs_path = os.path.abspath(image_path)
    log_func(f"📎 Mencoba attach media langsung ke input hidden: {os.path.basename(image_path)}")

    # XPath lebih spesifik untuk input file di composer FB (group/post)
    file_input_xpaths = [
        # Prioritas tinggi: mencocokkan accept attribute yang persis atau sangat mirip
    "//input[@type='file' and contains(@accept, 'image/*,image/heif,image/heic,video/*')]",

    # Variasi yang masih mencakup sebagian besar format
    "//input[@type='file' and contains(@accept, 'image/*') and contains(@accept, 'video/*') and contains(@accept, 'heif')]",

    # Lebih longgar tapi tetap spesifik ke image dan video
    "//input[@type='file'][contains(@accept, 'image') or contains(@accept, 'video') or contains(@accept, 'heic') or contains(@accept, 'heif')]",

    # Scoped ke composer (jika Facebook menaruh input di dalam div composer)
    "//div[contains(@class, 'composer') or contains(@role, 'dialog') or contains(@aria-label, 'posting')]//input[@type='file']",

    # Fallback paling aman: semua input file (ambil yang terakhir biasanya yang benar)
    "//input[@type='file']"
    ]

    file_input = None
    for xpath in file_input_xpaths:
        try:
            file_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            # Cek apakah ada di DOM (bahkan hidden)
            log_func(f"   ✓ Input file")
            break
        except:
            continue

    if not file_input:
        # Jika tetap tidak ketemu, coba cari semua input file dan ambil yang terakhir
        try:
            inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
            if inputs:
                file_input = inputs[-1]  # yang terbaru biasanya untuk media
                log_func("   → Fallback: ambil input file terakhir di DOM")
        except:
            log_func("   ❌ Tidak menemukan <input type='file'> sama sekali")
            return False

    try:
        # Paksa input visible sementara via JS (penting jika dialog muncul)
        driver.execute_script("""
            arguments[0].style.display = 'block';
            arguments[0].style.visibility = 'visible';
            arguments[0].style.opacity = '1';
            arguments[0].style.height = '1px';
            arguments[0].style.width = '1px';
            arguments[0].style.position = 'absolute';
        """, file_input)

        human_delay(0.5, 1.2)

        # Kirim path (harusnya tanpa dialog sekarang)
        file_input.send_keys(abs_path)
        log_func(f"   → Path dikirim: {abs_path}")

        human_delay(2, 4)

        # Kembalikan style asli jika perlu (opsional)
        driver.execute_script("arguments[0].style = '';", file_input)

        # Tunggu preview / tombol hapus muncul (tanda sukses attach)
        WebDriverWait(driver, 40).until(
            EC.presence_of_element_located((
                By.XPATH,
                "//img[contains(@src, 'blob:') or contains(@src, 'fbcdn')] | "
                "//video | "
                "//div[contains(@aria-label, 'Hapus') or contains(@aria-label, 'Remove')]"
            ))
        )
        log_func("   ✓ Preview media muncul")

        # Delay ekstra panjang supaya FB proses ke server
        human_delay(10, 20)
        log_func("   ✓ Delay selesai, upload kemungkinan sudah ke server")

        return True

    except Exception as e:
        log_func(f"   ❌ Gagal attach media: {str(e)}")
        return False

# ===================== BOT WORKER =====================
class BotWorker(QThread):
    log = pyqtSignal(str)
    groups_ready = pyqtSignal(list)

    def __init__(self, mode, text="", image="", max_groups=50, groups=None):
        super().__init__()
        self.mode = mode
        self.text = text
        self.image = image
        self.max_groups = max_groups
        self.groups = groups or []

    def run(self):
        options = Options()

        # ===== STEALTH MODE =====
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,900")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        driver.get("https://www.facebook.com/")
        human_delay(3,5)

        if not load_cookies(driver):
            self.log.emit("❌ cookies.json tidak ditemukan")
            driver.quit()
            return

        driver.get("https://www.facebook.com/")
        human_delay(5,7)
        self.log.emit("✅ Login sukses")

        if self.mode == "fetch":
            groups = fetch_groups_scroll(driver, self.max_groups, self.log.emit)
            save_groups(groups)
            self.groups_ready.emit(groups)

        elif self.mode == "post":
            for i, group in enumerate(self.groups, start=1):
                self.log.emit(f"➡ [{i}/{len(self.groups)}] {group}")
                driver.get(group)
                time.sleep(7.5)

                if not open_group_composer(driver):
                    self.log.emit("❌ Gagal membuka composer")
                    continue

                editor = wait_group_editor(driver)
                if not editor:
                    self.log.emit("❌ Editor tidak muncul")
                    continue

                ok = input_text_strict(driver, editor, self.text)
                if not ok:
                    self.log.emit("❌ Gagal memasukkan teks")
                    continue

                self.log.emit("📝 Teks berhasil dimasukkan")

                # Attach media (fungsi baru)
                media_success = False
                if self.image:
                    attach_media(driver, self.image, self.log.emit)
                    
                if media_success:
                    self.log.emit("   Media tampak terpasang → menunggu ekstra sebelum post")
                    human_delay(8, 15)

                post_btn = wait_post_button(driver)
                if not post_btn:
                    self.log.emit("❌ Tombol Posting tidak ditemukan / tidak aktif")
                    continue

                self.log.emit("🚀 Klik tombol Posting...")
                driver.execute_script("arguments[0].click();", post_btn)
                human_delay(5, 9)

                self.log.emit("✅ Posting ke grup berhasil")

        driver.quit()

# ===================== GUI =====================
class BotGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Versi 0.1 Contact Telegram : @jlimboo  :v")
        self.resize(700, 600)
        self._apply_dark_theme()

        layout = QVBoxLayout(self)

        self.postText = QTextEdit()
        self.postText.setPlaceholderText("Isi teks posting...")

        self.imagePath = QLineEdit()
        btnBrowse = QPushButton("Browse Image")
        btnBrowse.clicked.connect(self.browse_image)

        self.btnFetch = QPushButton("Ambil Group")
        self.btnLoad = QPushButton("Load Group File")
        self.btnPost = QPushButton("Posting Massal")

        self.groupList = QListWidget()
        self.logBox = QTextEdit()
        self.logBox.setReadOnly(True)

        layout.addWidget(QLabel("Text Post:"))
        layout.addWidget(self.postText)

        hl = QHBoxLayout()
        hl.addWidget(self.imagePath)
        hl.addWidget(btnBrowse)
        layout.addLayout(hl)

        layout.addWidget(self.btnFetch)
        layout.addWidget(self.btnLoad)
        layout.addWidget(QLabel("Daftar Group:"))
        layout.addWidget(self.groupList)
        layout.addWidget(self.btnPost)
        layout.addWidget(QLabel("Log:"))
        layout.addWidget(self.logBox)

        self.btnFetch.clicked.connect(self.fetch_groups)
        self.btnLoad.clicked.connect(self.load_group_file)
        self.btnPost.clicked.connect(self.post_massal)

    def browse_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih Gambar/Video", "", "Media Files (*.jpg *.jpeg *.png *.gif *.mp4 *.mov)")
        if path:
            self.imagePath.setText(path)

    def log(self, msg):
        self.logBox.append(msg)

    def fetch_groups(self):
        self.log("🔄 Mengambil daftar grup...")
        self.worker = BotWorker("fetch", max_groups=50)
        self.worker.log.connect(self.log)
        self.worker.groups_ready.connect(self.show_groups)
        self.worker.start()

    def load_group_file(self):
        groups = load_groups()
        self.groupList.clear()
        for g in groups:
            self.groupList.addItem(g)
        self.log("📂 Grup dimuat dari file groups.txt")

    def show_groups(self, groups):
        self.groupList.clear()
        for g in groups:
            self.groupList.addItem(g)
        self.log("💾 Daftar grup berhasil disimpan ke groups.txt")

    def post_massal(self):
        groups = [self.groupList.item(i).text() for i in range(self.groupList.count())]
        text = self.postText.toPlainText().strip()
        image = self.imagePath.text().strip()

        if not groups:
            self.log("⚠️ Tidak ada grup yang dipilih")
            return
        if not text:
            self.log("⚠️ Teks posting kosong")
            return

        if image and not os.path.exists(image):
            self.log(f"⚠️ File tidak ditemukan: {image}")
            image = ""

        self.log("🚀 Sedang Login... Tunggu 5 - 15 Detik")
        self.worker = BotWorker("post", text=text, image=image, groups=groups)
        self.worker.log.connect(self.log)
        self.worker.start()
    def _apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window,          QColor(24, 24, 28))
        palette.setColor(QPalette.WindowText,      QColor(225, 225, 235))
        palette.setColor(QPalette.Base,            QColor(32, 32, 38))
        palette.setColor(QPalette.AlternateBase,   QColor(38, 38, 46))
        palette.setColor(QPalette.Text,            QColor(225, 225, 235))
        palette.setColor(QPalette.Button,          QColor(40, 40, 48))
        palette.setColor(QPalette.ButtonText,      QColor(225, 225, 235))
        palette.setColor(QPalette.Highlight,       QColor(70, 130, 255))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)

        self.setStyleSheet("""
            QMainWindow {
                background: #18181c;
            }
            QLabel {
                color: #d0d0e0;
            }
            QTextEdit, QListWidget {
                background: #22222a;
                color: #e8e8f0;
                border: 1px solid #383844;
                border-radius: 9px;
                padding: 9px;
                selection-background-color: #4a6aff;
            }
            QPushButton {
                background: #34344a;
                color: #e0e0ff;
                border: 1px solid #4a4a60;
                border-radius: 9px;
                padding: 10px 20px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #44445c;
            }
            QPushButton:pressed {
                background: #28283c;
            }
            #btn_post {
                background: #0066ff;
                border: none;
                color: white;
            }
            #btn_post:hover {
                background: #0055dd;
            }
            #btn_stop {
                background: #e63946;
                border: none;
                color: white;
            }
            #btn_stop:hover {
                background: #d32f2f;
            }
            QProgressBar {
                background: #22222a;
                border: 1px solid #383844;
                border-radius: 9px;
                text-align: center;
                color: #d0d0e0;
            }
            QProgressBar::chunk {
                background: #0066ff;
                border-radius: 8px;
            }
            QSpinBox {
                background: #22222a;
                color: #e8e8f0;
                border: 1px solid #383844;
                border-radius: 7px;
                padding: 5px;
            }
        """)
# ===================== RUN =====================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = BotGUI()
    gui.show()
    sys.exit(app.exec_())
