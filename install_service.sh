#!/bin/bash
# Script cai dat Systemd Service tu dong khoi dong kem Linux khi co mang

if [ "$EUID" -ne 0 ]; then
  echo "Vui long chay script nay voi quyen sudo (Vi du: sudo ./install_service.sh)"
  exit 1
fi

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUN_SCRIPT="$PROJECT_DIR/run.sh"
SERVICE_NAME="chungkhoan.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
CURRENT_USER="${SUDO_USER:-$(whoami)}"

# Dam bao file run.sh co quyen thuc thi
chmod +x "$RUN_SCRIPT"

echo "Dang tao tao systemd service tai $SERVICE_PATH..."

cat > "$SERVICE_PATH" << EOF
[Unit]
Description=Chung Khoan Backend Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=/bin/bash $RUN_SCRIPT
Restart=always
RestartSec=3

# Môi trường cần thiết (tuỳ chọn thêm)
# Environment="PATH=/opt/conda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF

echo "Dang nap lai systemd daemon..."
systemctl daemon-reload

echo "Dang kich hoat service chay tu dong..."
systemctl enable "$SERVICE_NAME"

echo "Dang khoi dong service ngay bay gio..."
systemctl start "$SERVICE_NAME"

echo ""
echo "=========================================================="
echo "Cai dat thanh cong Tren Linux!"
echo "Server cua ban hien dang chay ngam (background) qua Systemd."
echo "Va se tu dong chay lai moi khi Raspberry Pi/VPS/Server Linux khoi dong va co ket noi mang."
echo ""
echo "Mot so lenh huu ich:"
echo "- De xem log: sudo journalctl -u $SERVICE_NAME -f"
echo "- De dung server: sudo systemctl stop $SERVICE_NAME"
echo "- De xem trang thai: sudo systemctl status $SERVICE_NAME"
echo "=========================================================="
