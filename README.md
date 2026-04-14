# XSMN Lottery Limit Manager

Hệ thống quản lý hạn mức lô đề Xổ Số Miền Nam - Tự động crawl, theo dõi 100 lô, thống kê thu/bù.

## Tính năng
- 🎯 Bảng 100 lô (00-99) với hạn mức color-coded
- 📉 Hạn mức giảm dần: 200đ → 180đ → ... → 10đ
- 🔥 Theo dõi lô về liên tiếp (2/3/4 ngày → cap 150/100/50đ)
- 📊 Thống kê thu/bù 30 ngày
- 🔄 Tự động crawl từ xsmn.mobi

## Chạy Local
```bash
# Windows
run.bat

# Hoặc thủ công
cd backend
pip install -r requirements.txt
python main.py
# Mở http://localhost:8899
```

## Tech Stack
- **Backend**: Python, FastAPI, SQLite, BeautifulSoup4
- **Frontend**: HTML, CSS, JavaScript, Chart.js
- **Data**: Crawl từ xsmn.mobi

## Deploy
Deployed on [Render.com](https://render.com) - Free tier
