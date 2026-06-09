<script lang="ts">
  import { onMount } from 'svelte';

  export let bestConn: any = null;

  let container!: HTMLDivElement;
  let updateInterval: ReturnType<typeof setInterval>;
  let myGlobe: any;

  async function fetchGlobeData() {
    const res = await fetch('http://localhost:3001/api/globe');
    const data = await res.json();

    if (!myGlobe) return;

    // Cập nhật vệ tinh
    myGlobe
      .pointsData(data.satellites)
      .pointLat((d: any) => d.lat)
      .pointLng((d: any) => d.lng)
      .pointAltitude((d: any) => d.alt)
      .pointColor((d: any) =>
        bestConn && d.name === bestConn.satellite ? '#22c55e' : '#facc15'
      )
      .pointRadius((d: any) =>
        bestConn && d.name === bestConn.satellite ? 0.15 : 0.08
      )
      .pointLabel((d: any) => `
        <div style="background:rgba(0,0,0,0.8);padding:5px 10px;border-radius:4px;border:1px solid #facc15;font-family:monospace;">
          🛰️ <b>${d.name}</b><br/>
          Alt: ${Math.round(d.alt * 6371)} km
        </div>
      `);

    // Cập nhật gateway từ data thay vì hardcode
    myGlobe
      .labelsData(data.gateways)
      .labelLat((d: any) => d.latitude_gateway)
      .labelLng((d: any) => d.longitude_gateway)
      .labelText((d: any) => d.name)
      .labelSize(1.5)
      .labelDotRadius(0.8)
      .labelColor(() => '#38bdf8')
      .labelResolution(2);
  }

  onMount(() => {
    const checkLibraries = () => {
      const GlobeConstructor = (window as any).Globe;
      const satellite = (window as any).satellite;
      if (!GlobeConstructor || !satellite) {
        setTimeout(checkLibraries, 100);
        return;
      }
      renderGlobe(GlobeConstructor);
    };
    checkLibraries();

    return () => {
      if (updateInterval) clearInterval(updateInterval);
      window.removeEventListener('resize', handleResize);
    };
  });

  const handleResize = () => {
    if (myGlobe && container) myGlobe.width(container.clientWidth);
  };

  function renderGlobe(GlobeConstructor: any) {
    myGlobe = GlobeConstructor()(container)
      .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')
      .bumpImageUrl('https://unpkg.com/three-globe/example/img/earth-topology.png')
      .backgroundImageUrl('https://unpkg.com/three-globe/example/img/night-sky.png')
      .width(container.clientWidth)
      .height(400)
      .pointOfView({ lat: 16, lng: 106, altitude: 2.5 });

    myGlobe.controls().autoRotate = true;
    myGlobe.controls().autoRotateSpeed = 0.2;
    window.addEventListener('resize', handleResize);

    // Fetch lần đầu rồi poll mỗi 5s
    fetchGlobeData();
    updateInterval = setInterval(fetchGlobeData, 5000);
  }
</script>