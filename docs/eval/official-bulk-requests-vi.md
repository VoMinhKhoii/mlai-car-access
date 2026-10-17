# Dự thảo yêu cầu dữ liệu chính thức — Ngõ Ngách

Soạn ngày 17/10/2026. **Chưa gửi**; chưa đăng ký tài khoản, chưa đặt hàng hoặc thanh toán. Điền thông tin người gửi và gửi qua đầu mối tiếp nhận chính thức. Không gửi giấy tờ định danh trong email đầu tiên; đề nghị hướng dẫn kênh nộp hồ sơ phù hợp nếu cần.

## 1. Thành phố: dữ liệu GIS trên diện rộng và tài khoản được cấp phép

Đầu mối có địa chỉ công khai: Trung tâm Chuyển đổi số `ttcds@tphcm.gov.vn` ([cổng dữ liệu mở](https://opendata.hochiminhcity.gov.vn/)); Sở Quy hoạch - Kiến trúc `sqhkt@tphcm.gov.vn` ([website Sở](https://qhkt.hochiminhcity.gov.vn/cai-cach-hanh-chinh/co-the-to-cao-qua-dien-thoai-email-mang-dien-tu-206.html)). Đề nghị chuyển tới đơn vị quản lý dữ liệu tương ứng tại Sở Xây dựng/Sở Nông nghiệp và Môi trường nếu cần. Hướng dẫn về tài khoản: [Sở KH&CN, 20/4/2026](https://dost.hochiminhcity.gov.vn/chuyen-doi-so/thanh-pho-ho-chi-minh-ban-hanh-quy-che-quan-ly-khai-thac-nen-tang-ban-do-so-dung-chung/).

**Tiêu đề:** Đề nghị hướng dẫn tiếp cận dữ liệu không gian giao thông, hẻm và lộ giới phục vụ nghiên cứu Ngõ Ngách

Kính gửi Quý Cơ quan,

Tôi là [họ tên], đại diện [nhóm/đơn vị, địa chỉ liên hệ]. Nhóm đang nghiên cứu Ngõ Ngách, công cụ hỗ trợ xác định liệu một loại ô tô cụ thể có thể tiếp cận địa chỉ trong mạng hẻm tại TP.HCM hay không. Đây là nghiên cứu về khả năng tiếp cận; chúng tôi phân biệt rõ chiều rộng sử dụng thực tế, chiều rộng nền/mặt đường và lộ giới quy hoạch.

Chúng tôi kính đề nghị được hướng dẫn thủ tục khai thác bộ dữ liệu hiện có trên phạm vi TP.HCM, ưu tiên:

1. Tim đường/hẻm, mép đường hoặc vùng mặt đường; thuộc tính tên, mã tuyến, chiều rộng hiện trạng, đơn vị đo, ngày khảo sát/cập nhật và cơ quan quản lý.
2. Chỉ giới đường đỏ, lộ giới hẻm được phê duyệt, đoạn áp dụng, số/ngày quyết định và lịch sử điều chỉnh. Chúng tôi sẽ lưu dữ liệu này riêng, không coi lộ giới là bề rộng thông thủy hiện tại.
3. Lớp ranh thửa hoặc phần hình học cần thiết để kiểm tra khoảng cách hai bên đường, không gồm tên chủ sử dụng, số giấy chứng nhận hay thông tin cá nhân.
4. Lớp giao thông thuộc CSDL nền địa lý tỷ lệ 1:2.000/1:5.000 và tài liệu mô tả thuộc tính.

Định dạng mong muốn là GeoPackage, GeoJSON, Shapefile hoặc một dịch vụ WFS/ArcGIS FeatureServer được cấp quyền tải theo vùng. Nếu dùng VN2000, xin cung cấp đầy đủ mã/hệ quy chiếu, múi chiếu, kinh tuyến trục, đơn vị và thông số chuyển đổi phù hợp. Nếu chưa thể cung cấp toàn thành phố, chúng tôi có thể bắt đầu với khu vực Bình Thạnh cũ để đối soát với 213 đoạn đường đã có số liệu tham chiếu.

Qua thử nghiệm công khai, ứng dụng `gisxaydung.tphcm.gov.vn/tracuuttqh` hỗ trợ xem bản đồ, nhưng dịch vụ đối tượng thửa đất yêu cầu quyền truy cập. Chúng tôi không sử dụng mã xác thực của người khác và không tìm cách vượt giới hạn truy cập. Kính đề nghị hướng dẫn đăng ký tài khoản được cấp phép, phạm vi dữ liệu được chia sẻ, giới hạn lưu lượng và phương thức tải hàng loạt phù hợp theo quy trình của Thành phố.

Xin cho biết điều kiện sử dụng, ghi nguồn, lưu bộ nhớ đệm, công bố số liệu dẫn xuất, chia sẻ lại và sử dụng trong sản phẩm; các khoản phí nếu có; cùng đầu mối kỹ thuật phụ trách. Chúng tôi sẵn sàng gửi thuyết minh nghiên cứu và hồ sơ theo yêu cầu trước khi tiếp nhận dữ liệu.

Trân trọng cảm ơn Quý Cơ quan.

[Họ tên — chức danh/nhóm — email — số điện thoại]

## 2. HCMGIS: định nghĩa trường và bộ dữ liệu đầy đủ

Địa chỉ trên [GeoReference](https://georeference.hcmgis.vn/view/114): `gis.skhcn@tphcm.gov.vn`; đây là địa chỉ từ footer của hệ thống, cần xác nhận còn phụ trách dữ liệu. Có thể nhờ Sở KH&CN (`skhcn@tphcm.gov.vn`, [địa chỉ công khai](https://dost.hochiminhcity.gov.vn/chuyen-doi-so/thanh-pho-ho-chi-minh-ban-hanh-quy-che-quan-ly-khai-thac-nen-tang-ban-do-so-dung-chung/)) chuyển đúng đơn vị.

**Tiêu đề:** Đề nghị xác nhận ngữ nghĩa, giấy phép và phiên bản mới của lớp hiện trạng lộ giới hẻm HCMGIS

Kính gửi Trung tâm/Đơn vị quản lý HCMGIS,

Nhóm [tên nhóm/đơn vị] đang nghiên cứu khả năng tiếp cận ô tô trong hẻm TP.HCM. Chúng tôi đã xem danh mục công khai tại `https://maps.hcmgis.vn/statistic` và tải một lần các lớp WFS được công bố công khai để đánh giá khả năng sử dụng dữ liệu, với truy vấn tuần tự và lưu bộ nhớ đệm.

Lớp `thuduc:ht_lg_hem_pla_line` có 355 đối tượng, trường `chieurong` và ngày phiên bản `2021-08-09T17:00:00Z`; lớp polygon tương ứng có 288 đối tượng. Phạm vi quan sát được nằm tại Phước Long A. Chúng tôi chưa sử dụng các số liệu này để kết luận khả năng xe đi qua hiện tại.

Kính nhờ Quý Đơn vị xác nhận:

- `chieurong` là bề rộng nền đường, mặt đường, lộ giới hiện hữu hay khoảng thông thủy; đơn vị và cách xác định, phạm vi áp dụng trên từng đối tượng.
- Ngày phiên bản có tương ứng ngày đo đạc không; trường `giatridochinhxacmatphang` có ý nghĩa và đơn vị gì; có phiên bản mới hơn hay không.
- Có bộ dữ liệu tương tự cho các phường/khu vực khác hoặc toàn TP.HCM, kèm nguồn quyết định và lịch sử thay đổi hay không.
- Giấy phép và điều kiện cho phép tải, lưu bản sao, ghép với OpenStreetMap, công bố thuộc tính dẫn xuất và phân phối lại dữ liệu/hình học. Mục Fees/AccessConstraints của WFS ghi NONE nhưng chúng tôi chưa tìm thấy giấy phép dữ liệu cụ thể.
- Địa chỉ được hỗ trợ để tải dữ liệu từ HCMGIS OpenData/Portal; một số tên miền hiện gặp lỗi xác thực chứng chỉ, nên chúng tôi chưa tiếp tục truy cập các tên miền đó.

Nếu cần ký thỏa thuận chia sẻ dữ liệu hoặc nộp hồ sơ nghiên cứu, xin hướng dẫn quy trình và đầu mối tiếp nhận. Chúng tôi ưu tiên một bản xuất GIS chính thức thay vì truy vấn lặp lại từng vị trí.

Trân trọng,

[Họ tên — đơn vị — email — số điện thoại]

## 3. Hồ sơ địa phương: phụ lục quyết định và bản đồ gốc

Gửi bộ phận tiếp nhận của đơn vị đang lưu hồ sơ sau sắp xếp hành chính; đề nghị Sở Quy hoạch - Kiến trúc hoặc Trung tâm Thông tin Quy hoạch chuyển tới đúng đơn vị. Không giả định quận cũ vẫn là cơ quan giải quyết hiện tại.

**Tiêu đề:** Đề nghị cung cấp bản điện tử phụ lục/bản đồ danh mục hẻm và lộ giới

Kính gửi Quý Cơ quan,

Để phục vụ nghiên cứu Ngõ Ngách về khả năng tiếp cận ô tô trong hẻm, nhóm [đơn vị] kính đề nghị được hướng dẫn tiếp cận bản điện tử bảng danh mục hẻm và bản đồ đính kèm các hồ sơ sau, cùng văn bản điều chỉnh/thay thế mới nhất:

- Quận Bình Thạnh cũ: hồ sơ quy định lộ giới hẻm dưới 12 m theo từng phường, bao gồm Quyết định 7906/QĐ-UBND ngày 20/12/2010 nếu thuộc hồ sơ lưu trữ của Quý Cơ quan.
- Quận Tân Phú cũ: Quyết định 3242/QĐ-UBND ngày 30/6/2017 về điều chỉnh, bổ sung danh mục lộ giới các tuyến đường, hẻm từ 12 m trở xuống và phụ lục đầy đủ.
- Quận 3 cũ: bản đồ tỷ lệ 1/500 đính kèm Quyết định 05/2008/QĐ-UBND ngày 18/11/2008, cho các phường 8–14 cũ.
- Quận Phú Nhuận cũ: phụ lục các cụm hẻm của Quyết định 1633/QĐ-UBND và 1634/QĐ-UBND ngày 14/5/2024; số liệu hiện trạng và hồ sơ hoàn công nếu đã hoàn thành nâng cấp.
- Quận 9 cũ: dữ liệu cập nhật/thay thế bảng hẻm trong Quyết định 01/2009/QĐ-UBND và bản đồ đoạn đường điều chỉnh theo Quyết định 09/2012/QĐ-UBND ngày 14/8/2012.

Ưu tiên tệp Excel/CSV có tên/mã hẻm, tuyến đường gốc, phường tại thời điểm lập, điểm đầu–cuối, chiều dài, bề rộng hiện trạng, lộ giới dự kiến, số/ngày quyết định; kèm bản đồ CAD/GIS hoặc PDF gốc để xác định đúng đoạn. Nếu chỉ có bản quét, chúng tôi có thể tự nhập lại và gửi danh sách cần đối chiếu.

Chúng tôi không đồng nhất lộ giới quy hoạch với chiều rộng thông thủy thực tế và không yêu cầu thông tin cá nhân/chủ sử dụng đất. Kính đề nghị thông báo tình trạng cập nhật, điều kiện sử dụng, ghi nguồn và phí cung cấp nếu có. Nếu hồ sơ đã chuyển đơn vị lưu trữ khác, xin hỗ trợ hướng dẫn đầu mối phù hợp.

Trân trọng,

[Họ tên — đơn vị — địa chỉ — email — điện thoại]

## 4. Quốc gia: dữ liệu nền địa lý không mật

Đầu mối công khai tại [Trung tâm Hạ tầng dữ liệu không gian địa lý](https://www.bandovn.vn/vi/co-so-du-lieu-nen-dia-ly-quoc-gia/thi-xa-go-cong-81077?AspxAutoDetectCookieSupport=1): `mapvn@mae.gov.vn`. Website hướng dẫn hồ sơ, tài khoản/chữ ký số và phí; chỉ đề nghị dữ liệu không mật, không đặt hàng tự động.

**Tiêu đề:** Đề nghị hướng dẫn cung cấp lớp giao thông không mật từ CSDL nền địa lý 1:2.000/1:5.000 tại TP.HCM

Kính gửi Trung tâm Hạ tầng dữ liệu không gian địa lý,

Tôi là [họ tên/đơn vị], đang thực hiện nghiên cứu Ngõ Ngách về khả năng tiếp cận phương tiện trong mạng đường hẻm TP.HCM. Kính đề nghị Trung tâm cho biết khả năng cung cấp **dữ liệu không mật** thuộc nhóm giao thông từ CSDL nền địa lý tỷ lệ 1:2.000 hoặc 1:5.000 cho khu vực TP.HCM.

Chúng tôi quan tâm lớp tim đường, mép đường/vùng đường, thuộc tính chiều rộng nền/mặt đường nếu có, mã và tên tuyến, thời điểm thu nhận/cập nhật, cấp chính xác cùng tài liệu mô tả. Xin xác nhận mức độ thể hiện đường nhỏ/hẻm, cách phân biệt chiều rộng thực đo với ký hiệu bản đồ và giới hạn sử dụng dữ liệu ở tỷ lệ tương ứng.

Xin hướng dẫn danh mục mảnh/khu vực, định dạng cung cấp, thông số hệ quy chiếu VN2000, bộ hồ sơ cần nộp, điều kiện cấp tài khoản, phí dự kiến, quyền sử dụng trong nghiên cứu/sản phẩm và quyền công bố thuộc tính dẫn xuất sau khi ghép với OpenStreetMap. Nếu có bộ dữ liệu mở đáp ứng nhu cầu này, kính nhờ Trung tâm cung cấp địa chỉ tải chính thức và điều kiện ghi nguồn.

Chúng tôi chỉ tiếp nhận dữ liệu thuộc phạm vi được phép cung cấp và sẽ hoàn thiện hồ sơ trước khi đặt hàng.

Trân trọng,

[Họ tên — đơn vị — email — điện thoại]

## 5. Nhóm nghiên cứu: dữ liệu chiều rộng hẻm tại điểm khảo sát

Gửi qua đầu mối tác giả/tổ chức trên bài báo hoặc thư viện; không suy đoán địa chỉ email. Áp dụng cho bài safety/network analysis tại Ward 2 District 5, nghiên cứu McGill của Justin Le và RMIT Hẻm archive.

**Tiêu đề:** Xin phép tiếp cận dữ liệu mạng hẻm và thuộc tính chiều rộng phục vụ nghiên cứu đối soát

Kính gửi Quý Tác giả/Nhóm nghiên cứu,

Nhóm [tên/đơn vị] đang nghiên cứu khả năng tiếp cận ô tô trong mạng hẻm TP.HCM. Qua công trình [tên công trình], chúng tôi nhận thấy nhóm có khảo sát hoặc phân loại chiều rộng hẻm tại [khu vực].

Xin hỏi nhóm có thể chia sẻ bảng thuộc tính và hình học các đoạn hẻm đã khảo sát, ngày khảo sát, định nghĩa chiều rộng, phương pháp đo/phân loại và sai số hoặc giới hạn phương pháp hay không. Nếu chỉ có phân loại trên/dưới ngưỡng 3,5 m, chúng tôi sẽ giữ nguyên dạng phân loại và không biến thành số đo liên tục. Không cần hình ảnh/ghi âm có thể nhận diện cá nhân hoặc dữ liệu hộ gia đình.

Chúng tôi mong được biết giấy phép, yêu cầu trích dẫn, phạm vi sử dụng nghiên cứu/sản phẩm và khả năng công bố dữ liệu dẫn xuất sau khi ghép với OpenStreetMap. Nếu không thể chia sẻ dữ liệu gốc, xin cân nhắc một tập mẫu đã lược bỏ thông tin nhạy cảm hoặc hỗ trợ xác nhận một số đoạn dùng để kiểm định.

Trân trọng,

[Họ tên — đơn vị — email — điện thoại]
