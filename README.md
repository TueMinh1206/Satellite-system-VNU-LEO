# Satellite System VNU-LEO

Dự án thiết kế và mô phỏng Hệ thống Vệ tinh VNU-LEO đảm bảo các yêu cầu sau:

- **Bài toán Quỹ đạo & Phủ sóng**: Lập trình tính toán và đề xuất số lượng vệ tinh LEO cần
thiết, cách sắp xếp quỹ đạo để đảm bảo phủ sóng liên tục toàn bộ Việt Nam. Phục vụ 2
ngành: Internet/VoIP (độ trễ thấp) và truyền tải dữ liệu Ảnh/Radar thời tiết (băng thông
cao).

- **Bài toán Gateway (Core Network)**: Lập trình mô phỏng quá trình duy trì phiên kết nối
và chuyển giao (Handover) khi vệ tinh di chuyển qua các Gateway đặt tại Hà Nội, Đà
Nẵng, TP. Hồ Chí Minh.

- **Bài toán Client (End-user Router)**: Xây dựng phần mềm trực quan hóa mô phỏng hoạt
động của Router người dùng. Phần mềm phải trực quan hóa được quá trình ăng-ten mảng
pha bám bắt vệ tinh, cập nhật các thông số C/N, suy hao, và chất lượng tín hiệu theo thời
gian thực.

## Tính năng chính
- **Backend**: Xử lý dữ liệu TLE (Two-Line Element), tính toán Azimuth, Elevation, Range và chất lượng tín hiệu (C/N ratio).
- **Frontend**: Dashboard thời gian thực sử dụng Svelte, tích hợp bản đồ 3D để trực quan hóa vị trí vệ tinh.
- **Hỗ trợ Handover**: Thuật toán lựa chọn kết nối tối ưu giữa Gateway và Router thông qua vệ tinh.

## Cấu trúc dự án
- `/server`: Mã nguồn Backend (Node.js/Express).
- `/gateway-dashboard`: Giao diện Dashboard (Svelte/Vite).
- `/LEO_Constellations_Design`: Tài liệu thiết kế và các file mô phỏng (Jupyter Notebook).
- `/Gateway` & `/Antena`: Thiết kế chi tiết trạm mặt đất và anten.
- `/data`: Chứa dữ liệu TLE và cấu hình vị trí các trạm.

## Hướng dẫn cài đặt và chạy

### 1. Chuẩn bị
Cài đặt [Node.js](https://nodejs.org/) (phiên bản 18 trở lên).

### 2. Chạy Backend
Mở một terminal mới:
```bash
cd server
npm install
node index.js
```
Server sẽ chạy tại: `http://localhost:3001`

### 3. Chạy Frontend
Mở một terminal khác:
```bash
cd gateway-dashboard
npm install
npm run dev
```
Truy cập giao diện tại: `http://localhost:5173`.

## Công nghệ sử dụng
- **Backend**: Express, `tle.js` (SGP4 propagation).
- **Frontend**: Svelte, Vite, `globe.gl`.
- **Nghiên cứu**: Python (Jupyter Notebook).

---
*Dự án được thực hiện bởi Nhóm 9 môn học truyền thông vệ tinh.*
