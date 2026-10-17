# Bộ đo hiện trường Ngõ Ngách

Đường dẫn dành cho điện thoại: `/field`. Thước dây và LiDAR là **Measured**, tầng bằng chứng mạnh nhất (CONTEXT.md, Q10–Q11). Bước chân chỉ là **Observed**. Các số đo nhập trong kiểm thử là giả lập và nằm trong thư mục tạm; CSV thật vẫn chưa có số đo hiện trường.

## Người vận hành: mở cho đồng đội

Chạy từ thư mục repo, dùng cùng checkout và filesystem với backend chính. Cần Python có dependencies của `requirements.txt`, `uvicorn`, Node/npm và `cloudflared` đã được cài. Không khởi chạy backend chính để đưa ra Internet.

1. Build cả hai entry:

   ```sh
   cd /Users/khoivo/Developer/mlai-car-access
   npm --prefix frontend run build
   ```

2. Đặt mã nhóm đủ dài trong terminal sẽ chạy server. Đổi chuỗi ví dụ bằng mã riêng rồi chia sẻ riêng cho đồng đội:

   ```sh
   export FIELD_TOKEN='thay-bang-ma-nhom-ngau-nhien-du-dai'
   python3 -m uvicorn app.field_server:app --app-dir backend --host 127.0.0.1 --port 8790
   ```

   Thử `http://127.0.0.1:8790/field` trên máy. Nhập mã nhóm một lần. Thiếu `FIELD_TOKEN` thì mọi API hiện trường trả 503, thiếu/sai mã trả 401. Mã gửi qua `Authorization: Bearer …`, không đặt trong URL. Trang và JS/CSS là tài nguyên tĩnh công khai; API của đội đo, ảnh và xác nhận cần mã. Các API crowd công khai được tách riêng và mô tả ở phần Crowd.

3. Ở terminal khác, **khi muốn chia sẻ**, chạy lệnh đã chuẩn bị sau (chưa chạy trong phiên triển khai):

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8790
   ```

   Sao chép URL `https://….trycloudflare.com` từ log, thêm `/field`, gửi cho đồng đội cùng mã nhóm qua kênh riêng. Đây là quick tunnel tạm thời; URL đổi khi mở tunnel mới. HTTPS cho phép điện thoại xin quyền GPS. Không tunnel cổng 8787 hoặc 5173.

4. Giữ cả hai terminal mở. Dừng tunnel bằng Ctrl+C sau buổi đo, rồi dừng field server. Máy ngủ hoặc mất mạng sẽ ngắt truy cập. URL mới là origin mới, nên các bản chờ trên URL cũ không tự xuất hiện ở URL mới; giữ URL cũ sống đến khi mọi máy báo **Chờ gửi 0**.

Field server chỉ lắp router hiện trường và `/field` cùng assets. Nó không import main/agent, không mở `/api/agent`, `/api/plan`, `/api/lookup/*`, `/api/ai/*`, `/api/flags`, `/api/budget`, `/api/area/build`, `/mcp` hay tài liệu API. Không có AI trả phí, Gemini hay cổng quy hoạch trong đường xử lý hiện trường. Queue và GPS snap đọc kho OSM local `backend/cache/live/evidence_inventory.json`. Có alias bảo vệ bằng token: `GET /api/evidence/queue` và `POST /api/confirm`.

Backend chính tự nạp file khi xử lý kế hoạch tiếp theo, không cần restart. Nếu dùng deployment/filesystem khác, phải đồng bộ CSV/ảnh/xác nhận về đúng máy chạy backend; tunnel không tự đồng bộ qua máy khác. `/api/plan` chỉ thử trên backend local, không nằm trong field server public.

## Đồng đội: đi đo bằng điện thoại

1. Mở link HTTPS `/field` bằng Safari trên iPhone hoặc Chrome trên Android. Nhập mã nhóm. Dùng điện thoại cá nhân, không đưa mã vào ảnh chụp màn hình.
2. Khi còn mạng, mở trang một lần, chờ thông báo trang đã sẵn sàng ngoại tuyến. Chọn khuôn viên HUTECH hoặc bấm **Dùng GPS của tôi** và cho phép vị trí chính xác. Chọn trường chỉ tìm đoạn gần trường; không dùng tọa độ trường thay cho vị trí đo.
3. Danh sách **Đo tiếp ở đâu?** lấy từ hàng chờ bằng chứng. Mỗi đoạn có Width Range hiện tại, tầng nguồn, lý do cần đo và ghim mở trên OpenStreetMap. Ghim là điểm đại diện đoạn, không phải vị trí chỗ hẹp nhất. Danh sách lấy các ưu tiên trong khu vực rồi xếp gần vị trí đã chọn; không bảo đảm liệt kê mọi đoạn đường.
4. Chọn đoạn, kiểm tra Way ID. GPS sẽ gợi ý đoạn gần nhất; ở ngã ba/hẻm song song phải đối chiếu ghim và tên, sửa Way ID nếu cần. GPS kém có thể ghép nhầm. Vị trí phải trong vùng TP.HCM ứng dụng hỗ trợ và cách hình học đoạn đã chọn không quá 150 m. Nếu GPS bị chặn, dùng tọa độ thực tế đã biết tại chỗ đo, nhập tay vĩ độ/kinh độ.
5. Đi bộ khảo sát đoạn được chọn, tìm phần **thông thủy hẹp nhất**: khoảng trống xe thật sự dùng được giữa các vật cản hai bên. Đo ngang vuông góc hướng đi, không đo chéo; không lấy lộ giới hoặc chỉ chiều rộng miệng hẻm làm số đo cả đoạn. Trừ bậc thềm, dốc lên nhà, chậu cây, xe máy đậu, sạp hàng. Ghi rõ vật cản tạm thời trong ghi chú.
6. Chọn thước dây / LiDAR / bước chân, nhập số mét (dùng `2,40` hoặc `2.40`). Chỉ đánh dấu **đã kiểm tra toàn bộ đoạn** khi thực sự đi hết Way và đo chỗ hẹp nhất. Nếu chỉ đo đầu hẻm hay một chỗ, để trống ô này và ghi mốc. Mẫu đó đặt giới hạn trên, không bảo đảm cả đoạn rộng như vậy.
7. Bấm **Lấy GPS** ngay tại điểm đo, thêm mốc như “đầu hẻm”, “chỗ hẹp nhất trước số 12”. Ghi vật cản, có/không/chưa kiểm tra khoảng quay cuối hẻm; nếu có, ghi rộng × dài khoảng trống. Đây là hiện trạng, chưa khẳng định mẫu xe nào quay được.
8. Thêm ảnh gốc nếu có (JPEG/PNG/WebP/HEIC, tối đa 8 MB), ghi tên rồi **Lưu số đo hiện trường**. Chụp thấy hai mép và vị trí đo; không cần khuôn mặt. Không quay chụp vào trong nhà khi chưa được phép.
9. Kiểm tra thông báo **Đã gửi** hoặc mục **Chờ gửi**. Không nhập số đo giả để thử trên dữ liệu thật.

## Thước dây

Nên đi hai người. Đứng nép ở vị trí an toàn, xin phép cư dân lịch sự, chờ dòng xe đi qua. Giữ dây ngang và thẳng giữa hai mép phần trống, không căng dây chắn đường khi xe đang tới. Đo lại 2–3 lần, ghi giá trị nhỏ nhất có thể lặp lại; kiểm tra thêm các chỗ thắt, khúc cua và lấn chiếm. Không đứng giữa dòng xe, không tự ý di chuyển tài sản người dân.

## iPhone Measure / LiDAR

Mở ứng dụng **Đo (Measure)**, dùng chế độ đo khoảng cách hai điểm trên mặt phẳng ngang của phần trống. Di chuyển máy chậm để ứng dụng nhận mặt phẳng; đặt điểm đầu ở một mép thông thủy, điểm cuối ở mép đối diện cùng mặt cắt. Đo lại vài lần từ vị trí khác, đối chiếu thước dây khi kết quả không ổn định. Không đo chéo giữa hai điểm khác độ cao hoặc đo từ mái/ban công.

Chỉ chọn **LiDAR** khi điện thoại thực sự có cảm biến LiDAR và đã dùng nó; ứng dụng Đo có thể hoạt động trên cả máy không có LiDAR. Nếu không có thước/cảm biến phù hợp, dùng **bước chân** và nhận tầng Observed, không tự gắn Measured. Sai số ±0,1 m (thước/LiDAR) và ±0,5 m (bước chân) trong engine là biên tạm thời của bộ đo, không phải chứng nhận độ chính xác thiết bị. Ảnh chụp màn hình kết quả Đo thường không có GPS; thêm vị trí qua nút GPS của biểu mẫu.

## Khi mất mạng hoặc bộ nhớ đầy

Bản gửi được ghi vào localStorage trước, có mã UUID chống trùng. Trang tự thử lại khi mạng trở lại, mỗi 30 giây khi đang mở, hoặc khi bấm **Gửi lại**. Việc gửi lại một bản không tạo số đo trùng. Thời điểm đo được giữ từ lúc bấm lưu, tách khỏi thời điểm máy chủ nhận.

Có thể mở lại `/field` ngoại tuyến sau khi service worker đã lưu thành công trang và assets. Danh sách HUTECH/xe/hẻm được nhớ trên máy; dữ liệu có thể cũ. Phải mở lần đầu khi có mạng, không có đồng bộ nền khi đóng tab. Không xóa dữ liệu trình duyệt/đổi origin trước khi hết bản chờ. Bản đang gõ chưa bấm lưu không được coi là bản chờ.

Ảnh base64 có thể vượt dung lượng localStorage. Nếu hiện **chưa gửi và chưa lưu được**, biểu mẫu vẫn giữ nguyên: giữ tab mở, chọn ảnh nhỏ hơn hoặc bỏ ảnh để gửi số đo trước, rồi thử lại. Không tuyên bố đã lưu khi bộ nhớ bị chặn hoặc đầy. Lỗi dữ liệu 422 giữ biểu mẫu để sửa; lỗi ở bản chờ cũ hiện ngay dưới bản đó. Có thể bỏ bản chờ sai sau khi ghi nhận lại đúng, nhưng thao tác bỏ sẽ xóa bản chưa gửi trên máy.

Ảnh lưu tại `backend/store/field_photos/` (không commit). Máy chủ giữ nguyên byte ảnh, bao gồm EXIF GPS nếu ảnh gửi lên có sẵn; trình duyệt/Photos có thể loại metadata trước lúc tải, hệ thống không tạo GPS EXIF mới. Nếu cần giữ GPS trên iPhone, chia sẻ/chọn bản gốc có bật dữ liệu vị trí. Chỉ người có mã nhóm mới tải được ảnh qua API; link ảnh không tự mang mã.

## Xác nhận sau khi đến và tích hợp UI chính

Tab **Đã đến nơi** là lời nhắc hiển thị độc lập: “Bạn đã đến — xe [model] vào được tới đâu?”. Chọn xe, lấy GPS và điền Way vừa thực sự đi qua. Ba nút: **Vào được / Vào được, chật / Không vào được**; có lựa chọn gập gương. Không xác nhận cho cả tuyến chưa đi qua.

Component được export từ `frontend/src/field/ArrivalConfirmation.tsx`, CSS có namespace riêng `arrival-*`. Chủ sở hữu UI chính có thể mount sau kết quả kế hoạch hoặc khi tài xế chủ động báo đã đến, ví dụ:

```tsx
import { ArrivalConfirmation } from './field/ArrivalConfirmation'

<ArrivalConfirmation
  vehicle={{ id: vehicle.id, label: vehicle.label }}
  lat={arrivalLat}
  lon={arrivalLon}
  wayIds={[actuallyTraversedWayId]}
  onConfirmed={() => refreshPlan()}
/>
```

Mặc định component POST `/api/confirm` hiện có. Field shell truyền sender có localStorage tới `/api/field/confirm`, handler có token, kiểm tra đầu vào và chống gửi trùng; field-only server cũng lắp chính handler đó ở `/api/confirm`. Cả hai ghi cùng `backend/store/confirmations.jsonl`; loader hiện có tạo Bound **Observed** với nguồn “Xác nhận sau khi đến” theo bề rộng xe/gương, không tạo Measured. Có thể truyền `endpoint`, `token`, `disabled` hoặc `submit(body)` cho component. Khi chưa có GPS/Way hợp lệ, vẫn thấy lời nhắc nhưng nút bị khóa. Không chỉnh `App.tsx`, `Result.tsx` hay `Agent.tsx` trong tác vụ này.

## Dữ liệu, nạp lại và kiểm thử

CSV `data/field/measurements.csv` giữ nguyên bảy cột đầu: `osm_way_id,alley_name,width_m,date,measured_by,note,photo_url`. Lần ghi đầu tiên tự thêm cột submission_id/source/method/lat/lon/accuracy_m/position_note/obstructions/turn_space/turn_width_m/turn_length_m/coverage_complete/recorded_at. Cột tùy biến và hàng cũ được bảo toàn. Ghi qua file tạm + fsync + os.replace, có flock cho nhiều tiến trình; không sửa từng phần file đang được đọc.

Hook nhỏ trong `evidence.py` gọi adapter `field_evidence.py`: thước/LiDAR Measured ±0,1 m; bước chân Observed ±0,5 m. Mẫu đơn có lower bound 0, upper bound số đo + biên, `estimate_m` và `coverage_complete=false`; khảo sát hết đoạn mới có lower bound số đo trừ biên. Hàng legacy chưa có method giữ cách hiểu thước dây. Các mâu thuẫn vẫn do engine hiện có xử lý, không ghi đè phép đo trước. Thông tin quay xe là metadata, chưa tự biến thành chứng nhận Way Out.

Mỗi kế hoạch kiểm tra timestamp/size của CSV và confirmations trước cache Width Range. Ghi ở field server riêng vì vậy có hiệu lực ở tiến trình backend chính trong lần yêu cầu tiếp theo, không cần gọi admin reload.

```sh
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p 'test_field_kit.py' -v
npm --prefix frontend run build
```

Kết quả tích hợp và số đo giả được tóm trong `docs/eval/field-e2e.json`; kiểm thử dùng CSV tạm và chặn kết nối socket cho E2E `/api/plan`. Có kiểm tra token/validation/ảnh nguyên byte/CSV tương thích/chống trùng/ghi đồng thời/nạp lại giữa hai tiến trình và bề mặt field server không có endpoint AI/admin. Ảnh mobile ở `docs/eval/field-*.png`. Các kiểm tra browser dùng viewport mobile Chromium; cần xác nhận GPS/camera trên iPhone/Android thật trong chuyến đo.

## Crowd cho khán giả hackathon (chưa đưa ra Internet)

Có ba trang dùng chung field-only server:

- `/field?crowd=1`: không đăng nhập. GPS → ghép hẻm → xác nhận trên sơ đồ nhỏ từ hình học OSM → thước dây hoặc iPhone Measure có LiDAR → ảnh phép đo bắt buộc và xác nhận ảnh thấy hai mép → gửi. Bước chân bị từ chối ở cả UI và API. Không cần tên; biệt danh tùy chọn.
- `/field/review`: cần mã nhóm. Đồng đội xem ảnh có bảo vệ, vị trí, phương pháp, số đo, rồi duyệt/từ chối với tên người duyệt và kết luận. Với Official phải đánh dấu đã đối chiếu địa chính trước khi duyệt.
- `/field/qr`: trang lớn để chiếu, QR tạo ngay trên máy từ `FIELD_PUBLIC_URL`, đếm số **hẻm khác nhau** đã được chấp nhận hôm nay theo giờ Việt Nam và sơ đồ điền các điểm OSM đã được đo. Tự cập nhật mỗi 5 giây. PENDING không làm tăng số hẻm Measured, có bộ đếm chờ riêng. Chưa có `FIELD_PUBLIC_URL` thì trang báo chưa cấu hình, không tạo link giả.

### Quyết định mở tunnel và khởi động sân khấu

Chưa chạy tunnel trong quá trình triển khai. Khi người vận hành quyết định mở, làm theo thứ tự sau:

1. Build `npm --prefix frontend run build`.
2. Trong terminal 1, chạy field server riêng bằng đúng lệnh dưới đây (đổi mã mẫu):

   ```sh
   cd /Users/khoivo/Developer/mlai-car-access
   export FIELD_TOKEN='thay-bang-ma-nhom-ngau-nhien-du-dai'
   export FIELD_TRUST_CLOUDFLARED=1
   python3 -m uvicorn app.field_server:app --app-dir backend --host 127.0.0.1 --port 8790
   ```

3. **Chỉ khi quyết định công khai**, terminal 2:

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8790
   ```

4. Lấy URL HTTPS `trycloudflare.com` trong log. Giữ tunnel đang chạy. Dừng riêng field server ở terminal 1 bằng Ctrl+C rồi khởi động lại cùng mã, thêm URL vừa có (không thêm token vào URL):

   ```sh
   export FIELD_PUBLIC_URL='https://URL-THUC-TE.trycloudflare.com'
   python3 -m uvicorn app.field_server:app --app-dir backend --host 127.0.0.1 --port 8790
   ```

5. Mở `/field/qr` trên màn chiếu. QR luôn mã hóa `https://URL-THUC-TE.trycloudflare.com/field?crowd=1`. Đồng đội mở `/field/review`, nhập `FIELD_TOKEN`; khán giả chỉ dùng crowd. Nếu chỉ kiểm tra local, có thể đặt `FIELD_PUBLIC_URL=http://127.0.0.1:8790` và không chạy cloudflared; mã đó chỉ dùng trên máy local.
6. Kết thúc: Ctrl+C tunnel trước, chờ gửi hết dữ liệu trên điện thoại rồi dừng server. Không bao giờ thay cổng tunnel bằng backend chính 8787. Giữ bí mật FIELD_TOKEN, không đưa mã vào slide/QR.

`FIELD_TRUST_CLOUDFLARED=1` chỉ dùng với server bind loopback phía sau cloudflared: đọc `CF-Connecting-IP` khi peer là 127.0.0.1/::1. Không bật khi ứng dụng trực tiếp nhận truy cập từ proxy không tin cậy. Nếu không bật, rate limit lấy IP socket, nên mọi khán giả có thể dùng chung một quota của tunnel và phải nhờ đồng đội duyệt.

### Chống lạm dụng và điều kiện dùng bằng chứng

Server cấp cookie thiết bị ngẫu nhiên có chữ ký HMAC, HttpOnly, SameSite=Lax. Cookie Secure trên HTTPS. Bản ghi chỉ giữ HMAC của thiết bị/IP, không giữ IP thô. Mỗi IP và thiết bị tối đa **10 lượt/giờ**; mỗi thiết bị tối đa **3 bản trên cùng Way** trong toàn vòng đời ledger. Kiểm tra trong transaction SQLite; gửi lại cùng UUID không tăng bản ghi/quota. Không tin device ID do client tự khai.

Mọi bản crowd được chèn PENDING trước. Chỉ thành Measured khi có người duyệt, hoặc có **hai cookie thiết bị do server cấp, hai IP/mạng khác nhau và ảnh khác nhau**, cùng Way, chênh số đo không quá 0,3 m. Máy dùng chung Wi-Fi hội trường sẽ giữ PENDING để đồng đội duyệt. Đây là kiểm soát lạm dụng thực dụng, không phải xác thực danh tính phần cứng. Cookie reset và nhiều mạng vẫn có thể bị lạm dụng; dùng trang duyệt khi cần tin cậy hơn.

Không tự động dùng crowd để vượt một Bound Official địa chính (khớp theo Way ID hoặc tên hẻm), kể cả khi Official được nạp sau lúc đã có đồng thuận. Duyệt tay cần xác nhận rõ đã đối chiếu Official. Planned lộ giới chỉ là metadata theo D49, không được giả làm Bound Official. Từ chối một bản trong cặp sẽ tính lại đồng thuận, không để bản còn lại giữ Measured khi mất nguồn độc lập.

Giá trị crowd phải **0,8–12 m**, có GPS trong vùng TP.HCM, đúng Way trong kho offline, cách đoạn ≤150 m, xác nhận chọn đúng hẻm, ảnh JPEG/PNG/WebP đọc được (≤8 MB, ≤20 megapixel) và xác nhận ảnh thực sự cho thấy phép đo ngang hẻm. Ảnh HEIC chưa giải mã được phải xuất JPEG tương thích. Server không dùng AI để phán nội dung ảnh; người duyệt phải kiểm tra phép đo rõ, đúng hẻm và không đo chéo. Hai ảnh hoặc đồng thuận không phải chứng nhận toàn đoạn.

Số đo crowd chỉ là mẫu tại một vị trí: lower bound 0, upper bound số đo +0,15 m (biên tạm thời), không chứng nhận cả hẻm. Khi **các số đo đã được chấp nhận** chênh quá 0,3 m, giữ khoảng hợp rộng và cờ REVIEW, không chọn một phép đo để che mâu thuẫn. Các bản PENDING bất đồng vẫn chờ duyệt và chưa thay đổi bằng chứng. Không sửa thuật toán fusion hiện có; adapter thêm cờ mâu thuẫn và khoảng hợp bảo thủ sau bước tổng hợp.

Crowd lưu ở `backend/store/field_crowd.sqlite`, ảnh ở `backend/store/crowd_photos/`, tách khỏi CSV của đội đo. Ảnh được giải mã rồi mã hóa lại JPEG, bỏ EXIF tên/chủ máy/make/model/serial/comment…; chỉ giữ GPS và thời điểm chụp nếu có. Trang công khai chỉ trả thống kê và điểm đại diện OSM, không trả biệt danh, GPS gốc, mã thiết bị, IP hay ảnh. Ảnh và hàng chờ chỉ qua endpoint có `FIELD_TOKEN`. Thông tin đo nhóm cũ vẫn giữ ảnh gốc theo brief ban đầu; quy tắc xóa EXIF áp dụng cho crowd.

Crowd cần mạng lúc gửi; nếu mất mạng, giữ trang/ảnh và thử lại, không có lời hứa đã lưu khi chưa gửi thành công. Luồng đồng đội vẫn có hàng chờ ngoại tuyến. Không có tunnel công khai nào được mở tự động từ trang QR hoặc server.

### Kiểm thử crowd

```sh
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p 'test_crowd_field.py' -v
```

Có kiểm tra cookie giả, không cần login, ảnh/GPS/phương pháp/giới hạn giá trị, rate limit, idempotency, PENDING chưa tạo Measured, đồng thuận độc lập, thu hồi đồng thuận, Official cần duyệt, khoảng mâu thuẫn + REVIEW, EXIF chỉ giữ GPS/thời gian, QR và counter không lộ thông tin cá nhân. Log ở `docs/eval/field-crowd-tests.txt`. Không thực hiện Gemini/portal calls.
