/**
 * Physics utilities for satellite link budget calculations.
 */

const SPEED_OF_LIGHT = 299792458; // m/s
const BOLTZMANN_CONSTANT = -228.6; // dBW/K/Hz

/**
 * Calculate Free Space Path Loss (FSPL) in dB.
 * @param {number} distanceKm - Distance between satellite and ground station in km.
 * @param {number} frequencyMHz - Frequency in MHz.
 * @returns {number} FSPL in dB.
 */
function calculatePathLoss(distanceKm, frequencyMHz) {
    // Formula: L = 20*log10(d) + 20*log10(f) + 32.44 (for km and MHz)
    return 20 * Math.log10(distanceKm) + 20 * Math.log10(frequencyMHz) + 32.44;
}

/**
 * Calculate C/N ratio (Carrier-to-Noise) in dB.
 * This is a simplified model.
 * @param {number} pathLoss - FSPL in dB.
 * @param {object} params - Satellite and Ground Station parameters.
 * @returns {number} C/N in dB.
 */
function calculateCN(pathLoss, params = {}) {
    const {
        eirp = 45,      // dBW (Typical for LEO)
        gt = 10,       // dB/K (Ground station G/T)
        bandwidth = 50, // MHz
    } = params;

    const bandwidthDb = 10 * Math.log10(bandwidth * 1e6);
    // C/N = EIRP - L + G/T - k - B (where k is Boltzmann's constant in dB)
    return eirp - pathLoss + gt - BOLTZMANN_CONSTANT - bandwidthDb;
}

/**
 * Map C/N and elevation to a signal quality percentage (0-100%).
 * @param {number} cn - C/N in dB.
 * @param {number} elevation - Elevation in degrees.
 * @returns {number} Signal Quality percentage.
 */
function calculateSignalQuality(cn, elevation) {
    // Basic mapping: 
    // Below 5dB C/N = 0%
    // Above 25dB C/N = 100%
    let quality = (cn - 5) / (25 - 5);

    // Penalty for low elevation (atmospheric interference)
    if (elevation < 10) {
        quality *= (elevation / 10);
    }

    return Math.max(0, Math.min(100, Math.round(quality * 100)));
}

module.exports = {
    calculatePathLoss,
    calculateCN,
    calculateSignalQuality
};
