/**
 * Network utilities for satellite network performance calculations.
 */

const SPEED_OF_LIGHT = 299792458; // m/s

/**
 * Calculate RTT latency in ms.
 * @param {number} rangeKm - Distance from router to satellite in km.
 * @returns {number} Latency in ms.
 */
function calculateLatency(rangeKm) {
    return ((2 * rangeKm * 1000) / SPEED_OF_LIGHT) * 1000;
}

/**
 * Calculate estimated ping in ms.
 * Includes processing delay at gateway/router.
 * @param {number} rangeKm - Distance from router to satellite in km.
 * @returns {number} Ping in ms.
 */
function calculatePing(rangeKm) {
    const latency = calculateLatency(rangeKm);

    // Add fixed processing delay
    return latency + 2;
}

/**
 * Calculate estimated throughput in Mbps.
 * Based on signal quality percentage.
 * @param {number} quality - Signal quality (0-100).
 * @returns {number} Throughput in Mbps.
 */
function calculateThroughput(quality) {
    const MAX_THROUGHPUT = 200;

    return Math.round((quality / 100) * MAX_THROUGHPUT);
}

/**
 * Calculate estimated packet loss percentage.
 * Based on C/N ratio.
 * @param {number} cn - Carrier-to-Noise ratio in dB.
 * @returns {number} Packet loss (%).
 */
function calculatePacketLoss(cn) {
    if (cn >= 20) return 0.1;
    if (cn >= 15) return 0.5;
    if (cn >= 10) return 2.0;

    return 5.0;
}

/**
 * Calculate estimated jitter in ms.
 * Lower elevation generally introduces more variation.
 * @param {number} elevation - Elevation angle in degrees.
 * @returns {number} Jitter in ms.
 */
function calculateJitter(elevation) {
    if (elevation > 60) return 1;
    if (elevation > 30) return 3;

    return 8;
}

/**
 * Calculate overall link score.
 * Used for satellite selection / handover decisions.
 * @param {object} metrics
 * @returns {number} Link score.
 */
function calculateLinkScore(metrics = {}) {
    const {
        quality = 0,
        cn = 0,
        elevation = 0
    } = metrics;

    return (
        quality * 0.5 +
        cn * 2 +
        elevation * 0.2
    );
}

module.exports = {
    calculateLatency,
    calculatePing,
    calculateThroughput,
    calculatePacketLoss,
    calculateJitter,
    calculateLinkScore
};