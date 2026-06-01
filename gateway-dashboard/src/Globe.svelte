<script lang="ts">
  import { onMount } from 'svelte';

  let container!: HTMLDivElement;
  let updateInterval: ReturnType<typeof setInterval>;
  let myGlobe: any;

  onMount(() => {
    // 1. VÒNG LẶP CHỜ: Đợi trình duyệt tải xong 2 thư viện từ Internet
    const checkLibraries = () => {
      // Lấy thư viện thẳng từ Window object (bỏ qua lệnh import)
      const GlobeConstructor = (window as any).Globe;
      const satellite = (window as any).satellite;

      // Nếu mạng chậm, thư viện chưa về kịp -> Đợi 100ms rồi kiểm tra lại
      if (!GlobeConstructor || !satellite) {
        setTimeout(checkLibraries, 100);
        return;
      }

      // 2. KHI ĐÃ ĐỦ THƯ VIỆN, BẮT ĐẦU VẼ ĐỊA CẦU
      renderGlobe(GlobeConstructor, satellite);
    };

    // Kích hoạt vòng lặp kiểm tra
    checkLibraries();

    // Dọn dẹp bộ nhớ khi chuyển trang
    return () => {
      if (updateInterval) clearInterval(updateInterval);
      window.removeEventListener('resize', handleResize);
    };
  });

  const handleResize = () => {
    if (myGlobe && container) myGlobe.width(container.clientWidth);
  };

  // HÀM VẼ ĐỊA CẦU (Đã được tách riêng cho gọn)
  function renderGlobe(GlobeConstructor: any, satellite: any) {
    myGlobe = GlobeConstructor()(container)
      .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
      .bumpImageUrl('https://unpkg.com/three-globe/example/img/earth-topology.png')
      .backgroundImageUrl('https://unpkg.com/three-globe/example/img/night-sky.png')
      .width(container.clientWidth)
      .height(400)
      .pointOfView({ lat: 16, lng: 106, altitude: 2.5 });

    myGlobe.controls().autoRotate = true;
    myGlobe.controls().autoRotateSpeed = 0.2;

    const gatewayData = [
      { lat: 21.0285, lng: 105.8542, name: 'GW-HN' },
      { lat: 16.0471, lng: 108.2068, name: 'GW-DN' },
      { lat: 10.8231, lng: 106.6297, name: 'GW-HCM' }
    ];

    myGlobe
      .labelsData(gatewayData)
      .labelLat((d: any) => d.lat)
      .labelLng((d: any) => d.lng)
      .labelText((d: any) => d.name)
      .labelSize(1.5)
      .labelDotRadius(0.8)
      .labelColor(() => '#38bdf8')
      .labelResolution(2);

    window.addEventListener('resize', handleResize);

    // BẮT ĐẦU ĐỌC DỮ LIỆU TLE TỪ FILE
    fetch('/tle_constellation_h1000_3x7.txt')
      .then(res => res.text())
      .then(text => {
        const lines = text.split('\n').map((l: string) => l.trim()).filter((l: string) => l.length > 0);
        const parsedTle: any[] = [];

        for (let i = 0; i < lines.length; i += 3) {
          if (lines[i] && lines[i+1] && lines[i+2]) {
            parsedTle.push({ name: lines[i], tle1: lines[i+1], tle2: lines[i+2] });
          }
        }

        const updateSatellites = () => {
          const now = new Date();
          const activeSatellites: any[] = [];

          parsedTle.forEach(sat => {
            try {
              const satrec = satellite.twoline2satrec(sat.tle1, sat.tle2);
              const positionAndVelocity = satellite.propagate(satrec, now);
              if (positionAndVelocity.position) {
                const gmst = satellite.gstime(now);
                const positionGd = satellite.eciToGeodetic(positionAndVelocity.position as any, gmst);
                activeSatellites.push({
                  name: sat.name,
                  lat: satellite.degreesLat(positionGd.latitude),
                  lng: satellite.degreesLong(positionGd.longitude),
                  alt: positionGd.height / 6371
                });
              }
            } catch (e) {
              // Bỏ qua vệ tinh bị lỗi tín hiệu/tính toán
            }
          });

          myGlobe
            .pointsData(activeSatellites)
            .pointLat((d: any) => d.lat)
            .pointLng((d: any) => d.lng)
            .pointAltitude((d: any) => d.alt)
            .pointColor(() => '#facc15')
            .pointRadius(0.08)
            .pointLabel((d: any) => `
              <div style="background: rgba(0,0,0,0.8); padding: 5px 10px; border-radius: 4px; border: 1px solid #facc15; font-family: monospace;">
                🛰️ <b>${d.name}</b><br/>
                Alt: ${Math.round(d.alt * 6371)} km
              </div>
            `);
        };

        updateSatellites();
        updateInterval = setInterval(updateSatellites, 1500);
      })
      .catch(err => console.error("Lỗi đọc file TLE:", err));
  }
</script>

<svelte:head>
  <script src="https://unpkg.com/globe.gl"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/satellite.js/4.1.3/satellite.min.js"></script>
</svelte:head>

<div class="globe-wrapper">
  <div bind:this={container} class="globe-container"></div>
</div>

<style>
  .globe-wrapper {
    width: 100%;
    display: flex;
    justify-content: center;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #1e293b;
    background-color: #000;
  }
  
  .globe-container {
    width: 100%;
    cursor: crosshair;
  }
  
  .globe-container:active {
    cursor: grabbing;
  }
</style>