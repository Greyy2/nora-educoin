# Hướng dẫn Cài đặt & Triển khai Chi tiết Hệ thống DCA (`SETUP.md`)

Tài liệu này cung cấp quy trình chuẩn hóa và đầy đủ để cài đặt, cấu hình và vận hành toàn bộ hệ thống kiểm thử chiến lược giao dịch **DCA Backtest** (tên mã: `norabt` / `Phoenix`).

---

## 📋 Mục lục
- [1. Yêu cầu Tiền đề (Prerequisites)](#1-yêu-cầu-tiền-đề-prerequisites)
- [2. Quy trình Cài đặt Chi tiết](#2-quy-trình-cài-đặt-chi-tiết)
  - [Bước 1: Clone Source Code từ Repository Git](#bước-1-clone-source-code-từ-repository-git)
  - [Bước 2: Cài đặt và Kích hoạt Môi trường Python Conda](#bước-2-cài-đặt-và-kích-hoạt-môi-trường-python-conda)
  - [Bước 3: Cài đặt & Cấu hình Cơ sở Dữ liệu (MySQL, MongoDB, Redis)](#bước-3-cài-đặt--cấu-hình-cơ-sở-dữ-liệu-mysql-mongodb-redis)
  - [Bước 4: Thiết lập Web Portal Backend & Frontend (`coins/`)](#bước-4-thiết-lập-web-portal-backend--frontend-coins)
  - [Bước 5: Thiết lập React Frontend của `coin_monitor`](#bước-5-thiết-lập-react-frontend-của-coin_monitor)
  - [Bước 6: Thu thập, Phân tích & Kiểm tra Dữ liệu Thị trường (Kline Data Pipeline)](#bước-6-thu-thập-phân-tích--kiểm-tra-dữ-liệu-thị-trường-kline-data-pipeline)
  - [Bước 7: Khởi chạy Cluster Tính toán `coin_service` (Phoenix Engine)](#bước-7-khởi-chạy-cluster-tính-toán-coin_service-phoenix-engine)
  - [Bước 8: Cấu hình Nginx Web Server cho Portal (`coins/`)](#bước-8-cấu-hình-nginx-web-server-cho-portal-coins)
  - [Bước 9: Thiết lập Hệ thống Lịch chạy Tự động (Crontab Scheduler)](#bước-9-thiết-lập-hệ-thống-lịch-chạy-tự-động-crontab-scheduler)
  - [Bước 10: Quy trình Chạy Kiểm thử Chiến thuật & Tối ưu hóa](#bước-10-quy-trình-chạy-kiểm-thử-chiến-thuật--tối-ưu-hóa)
- [3. Troubleshooting & Xử lý Lỗi thường gặp](#3-troubleshooting--xử-lý-lỗi-thường-gặp)

---

## 1. Yêu cầu Tiền đề (Prerequisites)

### 🖥️ Hệ điều hành & Phần cứng
- **Hệ điều hành**: Ubuntu 20.04 / 22.04 LTS (Khuyên dùng) hoặc Linux distribution tiêu chuẩn.
- **CPU**: Tối thiểu 8 cores (Khuyên dùng 16+ cores để hỗ trợ chạy tối ưu hóa tham số đa tiến trình).
- **RAM**: Tối thiểu 16 GB (Khuyên dùng 32 GB+ khi tải và xử lý tập dữ liệu lớn).
- **Dung lượng Ổ cứng**: **Tối thiểu 600 GB SSD/NVMe trống** (Dữ liệu nến 1m, 1s và Orderbook của hàng trăm cặp coin từ năm 2017 đến nay rất lớn).

### 🛠️ Phần mềm & Thư viện Yêu cầu
1. **Miniconda / Anaconda** (Python 3.9)
2. **PHP 7.2** (FastCGI / FPM) & **Composer**
3. **Node.js** (v14 hoặc v16 LTS) & **NPM**
4. **MySQL Server** (v5.7 hoặc v8.0)
5. **MongoDB Server** (v4.4 hoặc v5.0+)
6. **Redis Server** (v5.0+)
7. **Nginx** Web Server
8. **PM2** (Process Manager 2) cho Node/Python Services

---

## 2. Quy trình Cài đặt Chi tiết

### Bước 1: Clone Source Code từ Repository Git

Mở Terminal và clone dự án về máy chủ:

```bash
cd /var/www/html # Hoặc thư mục làm việc của bạn
git clone git@github.com:NORATN/DCA_backtest.git
cd DCA_backtest
```

---

### Bước 2: Cài đặt và Kích hoạt Môi trường Python Conda

Sử dụng file cấu hình [`lab.yml`](file:///Users/nevir/Desktop/DCA_backtest/lab.yml) để tạo tự động môi trường `lab` chứa tất cả thư viện Python phụ thuộc:

```bash
# Tạo môi trường conda từ file lab.yml
conda env create -f lab.yml

# Kích hoạt môi trường lab
conda activate lab

# Kiểm tra môi trường đã cài đặt thành công
python --version  # Output phải là Python 3.9.18
pip list
```

---

### Bước 3: Cài đặt & Cấu hình Cơ sở Dữ liệu (MySQL, MongoDB, Redis)

#### 3.1. Cài đặt MongoDB Server
```bash
sudo apt update
sudo apt install -y mongodb-org || sudo apt install -y mongodb
sudo systemctl start mongodb
sudo systemctl enable mongodb
sudo systemctl status mongodb
```

#### 3.2. Cài đặt MySQL Server
```bash
sudo apt update
sudo apt install -y mysql-server
sudo systemctl start mysql
sudo systemctl enable mysql
```

#### 3.3. Cài đặt Redis Server
```bash
sudo apt install -y redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

#### 3.4. Khôi phục Cơ sở Dữ liệu Schema MySQL
Khởi tạo cấu trúc bảng ban đầu cho MySQL từ file dump SQL hoặc migrations:

```bash
# Khởi tạo database 'coin_lab' và 'coin_db' trong MySQL
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS coin_lab CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS coin_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# Khôi phục schema cơ sở dữ liệu nếu có file sql backup (ví dụ: lab.sql hoặc các file sql sẵn có)
mysql -u root -p coin_lab < coins/database/laravel_itcjsc.sql
# Hoặc nếu bạn có file lab.sql sẵn trên máy chủ:
# mysql -u root -p coin_lab < lab.sql
```

---

### Bước 4: Thiết lập Web Portal Backend & Frontend (`coins/`)

`coins/` là cổng thông tin quản trị và điều hành chiến dịch viết bằng **Laravel 5.5 (PHP 7.2)**.

#### 4.1. Cài đặt PHP 7.2 và các Extension cần thiết:
```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:ondrej/php -y
sudo apt update

sudo apt install -y php7.2-cli php7.2-fpm php7.2-mbstring php7.2-xml \
                    php7.2-bcmath php7.2-curl php7.2-zip php7.2-tokenizer \
                    php7.2-ctype php7.2-fileinfo php7.2-mysql php7.2-gd \
                    php7.2-intl php7.2-mongodb
```

#### 4.2. Cài đặt Composer (nếu chưa có):
```bash
php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"
php composer-setup.php --install-dir=/usr/local/bin --filename=composer
php -r "unlink('composer-setup.php');"
composer --version
```

#### 4.3. Cài đặt PHP Packages & Cấu hình môi trường `.env`:
```bash
cd /var/www/html/DCA_backtest/coins

# Cài đặt PHP dependencies
composer install

# Khởi tạo file .env từ template
cp .env.exp .env

# Sinh APP_KEY cho Laravel
php artisan key:generate
```

Chỉnh sửa thông tin kết nối MySQL, MongoDB và Redis trong file `coins/.env` và `coins/config/database.php` phù hợp với máy chủ của bạn.

#### 4.4. Cài đặt Node.js Dependencies & Build Frontend Assets (Laravel Mix):
```bash
cd /var/www/html/DCA_backtest/coins

# Cài đặt frontend dependencies
npm install

# Biên dịch frontend assets cho môi trường Production
npm run prod
```

#### 4.5. Phân quyền Thư mục cho Web Server:
```bash
sudo chown -R www-data:www-data /var/www/html/DCA_backtest/coins
sudo find /var/www/html/DCA_backtest/coins -type f -exec chmod 644 {} \;
sudo find /var/www/html/DCA_backtest/coins -type d -exec chmod 755 {} \;
sudo chmod -R 775 /var/www/html/DCA_backtest/coins/storage
sudo chmod -R 775 /var/www/html/DCA_backtest/coins/bootstrap/cache
```

---

### Bước 5: Thiết lập React Frontend của `coin_monitor`

Thư mục `coin_monitor/frontend` chứa React Single-Page Application theo dõi thông số máy chủ.

```bash
cd /var/www/html/DCA_backtest/coin_monitor/frontend

# Cài đặt npm packages
npm install

# Build giao diện React công bố
npm run watch1 # Hoặc build tĩnh
```

---

### Bước 6: Thu thập, Phân tích & Kiểm tra Dữ liệu Thị trường (Kline Data Pipeline)

Chạy các lệnh quản lý trong môi trường Conda `lab` để tải và tính toán dữ liệu:

```bash
conda activate lab
cd /var/www/html/DCA_backtest/coin_monitor

# 6.1. Crawl dữ liệu nến 1 phút từ Binance API
python manage.py crawl_kline_1m_bulk

# 6.2. Phân tích dữ liệu & tính toán chỉ báo kỹ thuật (EMA, MACD, BUSD)
python manage.py process_kline_1m_bulk

# 6.3. Kiểm tra và xác minh tính toàn vẹn dữ liệu
python manage.py verify_data

# Hoặc chạy script kiểm tra dữ liệu rỗng ở thư mục gốc:
cd /var/www/html/DCA_backtest
python test.py
```

*Lưu ý:* Quá trình crawl và process ban đầu có thể kéo dài vài giờ tùy thuộc vào số lượng cặp coin và khoảng thời gian giao dịch cần mô phỏng.

---

### Bước 7: Khởi chạy Cluster Tính toán `coin_service` (Phoenix Engine)

`coin_service` bao gồm Socket.IO Hub Server (`lab_server`) và Worker Node Client (`lab_client`).

#### 7.1. Cấu hình file `.env` tại `coin_service/`:
```env
NODE_NAME = EXP
LAB_CENTER = http://127.0.0.1:5000
```

#### 7.2. Phương pháp 1: Khởi chạy bằng shell script nền (`start`/`stop`)
```bash
cd /var/www/html/DCA_backtest/coin_service

# Khởi chạy lab_client dưới nền
./start

# Dừng tiến trình
./stop
```

#### 7.3. Phương pháp 2: Khởi chạy chuẩn sản xuất bằng PM2 (Khuyên dùng)
Cài đặt PM2 toàn cục:
```bash
sudo npm install -y -g pm2
```

Khởi chạy cả `lab_server` và `lab_client` bằng PM2:
```bash
cd /var/www/html/DCA_backtest/coin_service

# Khởi chạy Socket Hub Server
pm2 start python --name "dca_lab_server" -- manage.py lab_server

# Khởi chạy Worker Node Client
pm2 start python --name "dca_lab_client" -- manage.py lab_client

# Lưu trạng thái tự khởi động cùng OS
pm2 save
pm2 startup
```

Kiểm tra trạng thái các service:
```bash
pm2 status
pm2 logs dca_lab_server
```

---

### Bước 8: Cấu hình Nginx Web Server cho Portal (`coins/`)

Tạo file cấu hình Nginx trỏ vào thư mục `coins/public`:

```bash
sudo nano /etc/nginx/sites-available/coin_backtest.conf
```

Dán nội dung cấu hình sau (thay thế `{port}` và đường dẫn tuyệt đối cho phù hợp):

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name _; # Hoặc tên miền của bạn

    root /var/www/html/DCA_backtest/coins/public;
    index index.php index.html index.htm;

    charset utf-8;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location = /favicon.ico { access_log off; log_not_found off; }
    location = /robots.txt  { access_log off; log_not_found off; }

    error_page 404 /index.php;

    location ~ \.php$ {
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/run/php/php7.2-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        include fastcgi_params;
    }

    location ~ /\.ht {
        deny all;
    }
}
```

Kích hoạt site và khởi động lại Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/coin_backtest.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

Bây giờ bạn có thể truy cập giao diện ứng dụng qua đường dẫn IP trình duyệt: `http://<IP_MAY_CHU>/admin` hoặc `http://<IP_MAY_CHU>/lab`.

---

### Bước 9: Thiết lập Hệ thống Lịch chạy Tự động (Crontab Scheduler)

Để ứng dụng tự động thu thập giá, chỉ số Fear & Greed Index, và theo dõi phần cứng máy chủ, nạp Crontab hệ thống:

```bash
# Nạp lịch từ file crontab của coins
crontab -l | cat - coins/coins | crontab -

# Nạp lịch cho coin_monitor agent
crontab -l | cat - coin_monitor/cron_coin_agent | crontab -
```

---

### Bước 10: Quy trình Chạy Kiểm thử Chiến thuật & Tối ưu hóa

1. **Khởi tạo Tài khoản Mô phỏng (Lab Account)**:
   Truy cập giao diện Web `/lab` hoặc chạy Artisan CLI để tạo tài khoản mô phỏng với số vốn ban đầu (ví dụ: \$10,000 USDT) và cấu hình đòn bẩy.
2. **Thiết lập Chiến dịch Backtest (Campaign)**:
   Định nghĩa cặp giao dịch (ví dụ `BTCUSDT`), chiều thế vị (`LONG`/`SHORT`), các tham số DCA entry phases, mức Take Profit, Stop Loss, Trailing Stop.
3. **Thực thi Chiến dịch Backtest**:
   ```bash
   cd /var/www/html/DCA_backtest/coins
   php artisan lab_run {campaign_id}
   ```
4. **Khởi chạy Tối ưu hóa Tham số (Parameter Optimization)**:
   ```bash
   cd /var/www/html/DCA_backtest/coin_service
   conda activate lab
   python manage.py lab_optimization {optimization_job_id}
   ```
5. **Xem Kết quả & Biểu đồ**:
   Truy cập giao diện Admin Portal `/admin` hoặc `/lab` để xem báo cáo thống kê PnL, đợt sụt giảm tài sản (Drawdown), lịch sử vào lệnh và biểu đồ equity curve.

---

## 3. Troubleshooting & Xử lý Lỗi thường gặp

### ❌ Lỗi thiếu PHP Extensions khi `composer install` / `composer update`
**Symptom**: Lỗi `The requested PHP extension ext-... is missing from your system`.
**Fix**: Cài bổ sung extension tương ứng bằng APT:
```bash
sudo apt install -y php7.2-<extension-name>
```

### ❌ Lỗi kết nối MongoDB `pymongo.errors.ServerSelectionTimeoutError`
**Symptom**: Không thể kết nối tới `mongodb://localhost:27017/`.
**Fix**: Kiểm tra trạng thái dịch vụ MongoDB và file cấu hình `/etc/mongod.conf`:
```bash
sudo systemctl status mongodb
sudo systemctl restart mongodb
```

### ❌ Cảnh báo hết dung lượng ổ cứng (Disk Usage Warning)
**Symptom**: Agent Telegram gửi cảnh báo đĩa SSD/HDD đầy trên 95%.
**Fix**: Chạy các công cụ làm sạch dữ liệu nến thừa hoặc dữ liệu log tạm:
```bash
cd coins
php artisan clean_candle_data
php artisan clean_lab_data
```

---
*Tài liệu Cài đặt Hệ thống DCA được tổng hợp và kiểm tra chuẩn hóa dựa trên codebase thực tế.*
