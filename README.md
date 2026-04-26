# Lottery Limit Manager - 3 Miền

Hệ thống quản lý hạn mức lô đề Xổ Số 3 Miền - Tự động crawl, theo dõi 100 lô, thống kê thu/bù.

## Tính năng
- 🌴🏯⛩️ Hỗ trợ 3 miền: **Miền Nam**, **Miền Bắc**, **Miền Trung**
- 🎯 Bảng 100 lô (00-99) với hạn mức color-coded (riêng từng miền)
- 📉 Hạn mức giảm dần: 200đ → 180đ → ... → 10đ
- 🔥 Theo dõi lô về liên tiếp (2/3/4 ngày → cap 150/100/50đ)
- 📊 Thống kê thu/bù 30 ngày (riêng từng miền)
- 🔄 Tự động crawl từ xsmn.mobi & xskt.com.vn

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
- **Data Sources**: 
  - Miền Nam: crawl từ xsmn.mobi
  - Miền Bắc & Trung: crawl từ xskt.com.vn

## Deploy
Deployed on [Render.com](https://render.com) - Free tier
