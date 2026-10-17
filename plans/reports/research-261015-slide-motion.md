# Vào Được: nghiên cứu và cải thiện slide động

## Tóm tắt

- Thực hiện: 2026-10-15, khoảng 17:03 UTC+7.
- Đầu ra: `docs/submission/Vao-Duoc-Slides.html` và `docs/submission/Vao-Duoc-Slides.pdf`.
- Giữ 11 slide và hình app hiện có. HTML có chuyển cảnh, reveal từng ý, tổng quan, fullscreen, sáng/tối, bật/tắt motion. PDF hiển thị toàn bộ nội dung tĩnh.
- Không sửa app, không thay đổi dữ liệu demo, không thêm dependency hoặc số liệu thị trường.

## Phạm vi và phương pháp

Đọc Atlas người dùng cung cấp, chọn pattern liên quan tới presentation/motion/accessibility, đối chiếu tài liệu chính thức MDN. Một truy vấn web; hai tài liệu MDN đọc trực tiếp. Không nghiên cứu lại thị trường hay đánh giá model AI. Chỉ tuyên bố những hành vi đã kiểm tra trên trình duyệt.

## Nguồn và áp dụng

| Nguồn | Áp dụng |
|---|---|
| `/home/pearspringmind/Downloads/UIUX_Resource_Atlas_Universal_Agent_Guide_v2.html`, `selection_rules`, WF05, X17 | Giữ công nghệ hiện có; chọn motion có mục đích; reduced-motion; kiểm tra mobile và print |
| [MDN Element.animate](https://developer.mozilla.org/en-US/docs/Web/API/Element/animate) | Native Web Animations API cho transform/opacity; hủy animation cũ khi đổi slide nhanh |
| [MDN prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion) | Tôn trọng tùy chọn hệ điều hành, cộng nút tắt chuyển động thủ công |
| Các reference `ak-preview` và `ak-frontend-design` đã cài | Hierarchy, bố cục trình chiếu, typography và nhịp reveal |

Atlas có GSAP/Motion trong danh mục nhưng đây không phải lý do để thêm dependency. Không sao chép mã hay tải asset từ các thư viện đó.

## Lựa chọn kỹ thuật

| Cách | Đánh đổi | Quyết định |
|---|---|---|
| Native CSS + Web Animations API | Tự viết state slide/reveal; không cần CDN hoặc build | Chọn cho deck HTML offline hiện có |
| Thêm animation library | Có API timeline tiện hơn nhưng phải đóng gói và quản lý thư viện | Không cần cho các hiệu ứng hiện tại |
| Chỉ PDF | Dễ gửi, không có tương tác | Giữ làm đầu ra bổ sung, không thay HTML |

## Thiết kế và tương tác

- Teal giữ nhận diện app; bìa có ảnh sản phẩm, nội dung dùng bố cục ảnh + callout, pipeline và các khối phẳng thay vì thẻ đồng loạt.
- Chuyển slide bằng translate/crossfade/scale nhẹ; reveal ý riêng bằng transform/opacity. Không tự chạy vô hạn hoặc tự chuyển slide.
- `Space`, `→`, `↓`: hiện ý kế tiếp rồi chuyển slide. `←`, `↑`: lùi nhịp.
- `PageDown` / `PageUp`: chuyển thẳng slide; `Home` / `End`: đầu/cuối.
- `O`: tổng quan 11 slide; `F`: fullscreen; `M`: bật/tắt chuyển động.
- Mobile reflow một cột, đọc dọc, hỗ trợ vuốt ngang. Thanh điều khiển không điều hướng khi bấm các nút phụ.
- Print tắt toolbar, reveal và animation; mọi nội dung hiện sẵn. Không có JavaScript trong PDF.

## An toàn, hiệu năng và khả năng tiếp cận

- Không gọi API app, không dùng credentials hay tài nguyên mạng; ảnh nhúng data URI.
- Hoạt ảnh giới hạn theo thao tác, không chạy nền vô hạn. Không công bố điểm benchmark hoặc tuân thủ WCAG toàn phần khi chưa đo/audit.
- Nút có tên và focus-visible; dialog tổng quan có nhãn, đóng bằng Escape; slide không hoạt động dùng inert/aria-hidden.
- Khi JavaScript tắt, cả 11 slide vẫn hiện để đọc. Thiết bị không hỗ trợ fullscreen nhận thông báo dùng chế độ trình duyệt.

## Xác minh đã thực hiện

- Mở trực tiếp file HTML bằng Chromium, thấy chuyển cảnh đang chạy; reveal tiến/lùi đổi đúng số ý.
- Tổng quan: 11 nút slide; chọn được slide; Escape đóng dialog.
- Fullscreen mở thật, trạng thái aria-pressed cập nhật true.
- End: 11/11, nút tiếp bị vô hiệu hóa; không còn ý ẩn ở slide cuối.
- Tắt motion thủ công: không có animation chạy; giả lập OS reduced-motion: 0 animation chạy.
- 375px: cả 11 slide sau khi animation kết thúc có document/deck width 375px; không có tràn ngang. Đã sửa specificity ảnh trên mobile và giới hạn chuyển động trong container.
- JavaScript tắt: 11 slide hiển thị; 0 request HTTP(S) khi chạy offline; không ghi nhận lỗi JavaScript.
- Print media: 11 slide hiển thị, 0 build bị ẩn; kiểm tra bounding boxes không có nội dung văn bản/ảnh chính tràn trang.
- PDF cuối: 11 trang, 960 × 540 pt (16:9), JavaScript: no. Đã render contact sheet và xem toàn bộ bố cục; đã loại trang trắng thứ 12.

## Chỉnh sửa kể chuyện gần người dùng hơn

- Mở bằng tình huống tài xế đến đầu hẻm; câu hỏi đặt ra không phải lời trích dẫn khách hàng.
- Giữ 11 chủ đề, thay câu chữ kiểu báo cáo bằng câu hỏi và hành động: chọn xe, đánh lái, đỗ, về, kể lại.
- Dùng Noto Serif cho tagline/câu hỏi; Noto Sans cho nội dung và điều khiển. Bố cục câu hỏi lớn + ba nỗi lo, đoạn giải thích ba cột và ảnh app giữ vai trò riêng.
- Chỉ rõ VETC/bảo hiểm/cứu hộ là hướng tích hợp đề xuất, không phải dịch vụ đã kết nối trong demo.
- Reveal slide mở vấn đề giữ câu hỏi chính hiện ngay, ba câu hỏi phụ xuất hiện theo nhịp.
- Đã xem bìa HTML và bản mobile; kiểm tra 11 slide ở 375px không tràn ngang, tổng quan/reveal hoạt động, không có lỗi JS. PDF đã xuất lại đủ 11 trang 16:9 và xem toàn bộ contact sheet; không có chữ/ảnh chính tràn trang hoặc reveal bị ẩn.

## Bước tiếp theo

1. Mở HTML trên máy thuyết trình, dùng F để toàn màn hình.
2. Dùng Space để diễn giải từng ý; PageDown nếu muốn bỏ qua nhịp.
3. Dùng PDF khi gửi ban tổ chức hoặc trình chiếu tĩnh.

## Giới hạn và câu hỏi còn lại

- Đây là HTML và PDF, không phải file PowerPoint/Canva có thể chỉnh sửa trong các ứng dụng đó.
- Chưa kiểm tra trên điện thoại thật hoặc trình duyệt ngoài Chromium; font có thể dùng fallback của hệ điều hành.
- Chưa commit/push các thay đổi slide trong lượt này.
