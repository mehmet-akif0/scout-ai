# Scout AI

Girişimleri keşif listesinde toplamak ve yatırım fırsatlarını değerlendirmek için Türkçe startup scouting uygulaması.

## Gereksinimler ve kurulum

Node.js 24 veya üzeri ve npm gerekir. Uygulama Node'un yerleşik HTTP ve SQLite modüllerini kullanır; üçüncü taraf çalışma zamanı bağımlılığı veya API anahtarı gerekmez. Node bazı sürümlerde SQLite için deneysel özellik uyarısı verebilir.

```sh
npm ci
npm start
```

Tarayıcıda `http://127.0.0.1:3000` adresini açın. Geliştirme sırasında otomatik yeniden başlatma için `npm run dev` kullanın.

## İlk kullanım

1. **Girişim ekle** ile ad, sektör, aşama, konum, site, açıklama, 0–100 puan ve notları girin.
2. Girişimleri metin, sektör ve takip durumuna göre filtreleyin. Liste yüksek puandan düşüğe sıralanır.
3. **İncele** ile bilgileri, puanı ve takip durumunu güncelleyin veya kaydı silin.
4. **JSON dışa aktar** tüm kayıtların taşınabilir bir kopyasını indirir. Bu sürümde JSON içe aktarma bulunmaz.

İlk açılışta liste boştur; gerçek girişimler veya yapay veriler otomatik eklenmez. Puanlar kullanıcı tarafından girilir. AI analizi, otomatik internet taraması ve harici veri sağlayıcıları bu ilk sürüme dahil değildir.

## Veri ve ayarlar

Veriler `data/scout.db` içinde SQLite ile kalıcı saklanır. `data/` Git dışında tutulur. Yedek almak için uygulamayı durdurup tüm `data/` klasörünü kopyalayın; geri yüklerken de uygulamayı durdurun.

- `PORT`: Varsayılan `3000`.
- `HOST`: Varsayılan `127.0.0.1`. Container erişimi gerekiyorsa `0.0.0.0` kullanın.
- `DB_PATH`: Varsayılan depo kökündeki `data/scout.db`; alternatif veritabanı yolu.

Bu sürüm tek ekip için yerel bir prototiptir; kullanıcı girişi ve erişim kontrolü içermez. Her erişen aynı kayıtları okuyabilir ve değiştirebilir. İnternete açmadan önce kimlik doğrulama, HTTPS ve erişim kontrolü ekleyin.

## Doğrulama

```sh
npm test
```

Entegrasyon testi geçici SQLite veritabanı ve gerçek HTTP sunucusu ile CRUD, giriş doğrulaması, statik dosyalar ve yeniden başlatma sonrası veri kalıcılığını kontrol eder. Test verileri gerçek veritabanına yazılmaz.

Sağlık kontrolü: `GET /api/health` → `{"status":"ok"}`.

## Proje yapısı

- `server.js`: HTTP sunucusu, API ve SQLite kalıcılığı.
- `public/`: Duyarlı arayüz, arama/filtreleme ve düzenleme formu.
- `test/app.test.js`: HTTP entegrasyon testi.

Üretim derleme adımı gerekmez. JavaScript ve CSS doğrudan sunulur.
