# Satellite System VNU-LEO

Dự án nghiên cứu và thiết kế hệ thống vệ tinh quỹ đạo thấp (LEO) tập trung vào tính toán quỹ đạo, ngân sách liên kết (link budget) và quản lý trạm mặt đất.

## Tính năng chính
- **Backend**: Xử lý dữ liệu TLE (Two-Line Element), tính toán Azimuth, Elevation, Range và chất lượng tín hiệu (C/N ratio).
- **Frontend**: Dashboard thời gian thực sử dụng Svelte, tích hợp bản đồ 3D để trực quan hóa vị trí vệ tinh.
- **Hỗ trợ Handover**: Thuật toán lựa chọn kết nối tối ưu giữa Gateway và Router thông qua vệ tinh.

##Cấu trúc dự án
- `/server`: Mã nguồn Backend (Node.js/Express).
- `/gateway-dashboard`: Giao diện Dashboard (Svelte/Vite).
- `/LEO_Constellations_Design`: Tài liệu thiết kế và các file mô phỏng (Jupyter Notebook).
- `/Gateway` & `/Antena`: Thiết kế chi tiết trạm mặt đất và anten.
- `/data`: Chứa dữ liệu TLE và cấu hình vị trí các trạm.

## Hướng dẫn cài đặt và chạy

### 1. Chuẩn bị
Đảm bảo bạn đã cài đặt [Node.js](https://nodejs.org/) (phiên bản 18 trở lên).

### 2. Chạy Backend
Mở một terminal mới:
```bash
cd server
npm install
npm start
```
Server sẽ chạy tại: `http://localhost:3001`

### 3. Chạy Frontend
Mở một terminal khác:
```bash
cd gateway-dashboard
npm install
npm run dev
```
Truy cập giao diện tại: `http://localhost:5173` (hoặc cổng được hiển thị trên console).

## Công nghệ sử dụng
- **Backend**: Express, `tle.js` (SGP4 propagation).
- **Frontend**: Svelte, Vite, `globe.gl`.
- **Nghiên cứu**: Python (Jupyter Notebook).

---
*Dự án được thực hiện bởi Nhóm nghiên cứu thiết kế hệ thống LEO.*
