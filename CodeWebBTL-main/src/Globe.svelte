<script lang="ts">
  import { onMount } from 'svelte';
  import Globe from 'globe.gl';

  let container!: HTMLDivElement;

  onMount(() => {
    // Ép kiểu Globe thành 'any' để lách luật lỗi 2348 của TypeScript
    const GlobeConstructor = (Globe as any);

    // Khởi tạo quả địa cầu 3D
    const myGlobe = GlobeConstructor()(container)
      .globeImageUrl('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg') 
      .bumpImageUrl('https://unpkg.com/three-globe/example/img/earth-topology.png')     
      .backgroundImageUrl('https://unpkg.com/three-globe/example/img/night-sky.png')    
      .width(container.clientWidth)
      .height(350)
      .pointOfView({ lat: 16, lng: 106, altitude: 1.5 }); 

    myGlobe.controls().autoRotate = true;
    myGlobe.controls().autoRotateSpeed = 0.5;

    const gatewayData = [
      { lat: 21.0285, lng: 105.8542, name: 'GW-HN' },
      { lat: 16.0471, lng: 108.2068, name: 'GW-DN' },
      { lat: 10.8231, lng: 106.6297, name: 'GW-HCM' }
    ];

    // Khai báo rõ (d: any) để khắc phục lỗi 7006
    myGlobe
      .labelsData(gatewayData)
      .labelLat((d: any) => d.lat)
      .labelLng((d: any) => d.lng)
      .labelText((d: any) => d.name)
      .labelSize(1.5)
      .labelDotRadius(0.8)
      .labelColor(() => '#38bdf8') 
      .labelResolution(2);

    const handleResize = () => {
      myGlobe.width(container.clientWidth);
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  });
</script>

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
    cursor: grab; 
  }
  
  .globe-container:active {
    cursor: grabbing;
  }
</style>