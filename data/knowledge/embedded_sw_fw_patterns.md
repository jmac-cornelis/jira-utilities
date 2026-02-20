# Embedded SW/FW Development Patterns

Common patterns and considerations for software/firmware development at Cornelis Networks.

## Firmware Development Patterns

### Device Initialization
- Power-on reset sequence: clock enable → reset deassert → register init → self-test
- Configuration loading: read from EEPROM/flash, validate, apply defaults for missing fields
- Health check: verify device ID register, run BIST, report status

### Register Access Layer
- Memory-mapped I/O for PCIe devices (BAR mapping)
- SPI/I2C transactions for peripheral devices
- Bit-field definitions with read-modify-write helpers
- Register access logging for debug builds

### State Machines
- Operational states: INIT → READY → ACTIVE → ERROR → RECOVERY
- Event-driven transitions with timeout handling
- State persistence across warm resets

### Interrupt Handling
- MSI-X for PCIe devices (one vector per event type)
- GPIO interrupts for peripheral events
- Top-half / bottom-half split for latency-sensitive paths
- Interrupt coalescing for high-frequency events

### DMA Engine
- Descriptor ring buffers (TX and RX)
- Scatter-gather support for large transfers
- Completion interrupts or polling modes
- Cache coherency considerations (dma_alloc_coherent)

### Error Handling
- Hardware error detection (ECC, CRC, parity)
- Error counters and thresholds
- Automatic recovery for transient errors
- Fatal error reporting and graceful degradation

## Driver Development Patterns

### Linux Kernel Module Structure
```
module_init() → register PCI/platform driver
  probe()    → map BARs, request IRQs, create sysfs, register netdev
  remove()   → reverse of probe
module_exit() → unregister driver
```

### PCIe Driver Essentials
- PCI ID table for device matching
- BAR mapping with pci_iomap() / pci_iounmap()
- MSI-X allocation with pci_alloc_irq_vectors()
- DMA mask setting with dma_set_mask_and_coherent()

### Sysfs / Debugfs Interfaces
- Sysfs for user-facing configuration (persistent, documented)
- Debugfs for developer-facing debug info (not ABI-stable)
- Attribute groups for organized parameter exposure

### User-Space API Patterns
- ioctl for control-plane operations
- mmap for shared memory / register access
- netlink for event notification
- Character device for streaming data

### Power Management
- Suspend: save state → disable interrupts → power down
- Resume: power up → restore state → enable interrupts
- Runtime PM for idle power savings

## Tool Development Patterns

### CLI Tool Structure
- Subcommand pattern (e.g., `opatool info`, `opatool config`, `opatool test`)
- Consistent output formatting (table, JSON, CSV)
- Verbose/quiet modes
- Return codes: 0 = success, 1 = error, 2 = warning

### Diagnostic Utilities
- Register dump (all registers with decoded field names)
- Link test (loopback, PRBS pattern)
- Health check (temperature, voltage, error counters)
- Firmware version reporting

## Testing Patterns

### Unit Testing
- Mock hardware access (register read/write stubs)
- Test each state machine transition
- Boundary value testing for configuration parameters
- Error injection for error-handling paths

### Integration Testing
- Driver load/unload cycles
- Device reset and recovery
- Multi-device scenarios
- Concurrent access testing

### Performance Testing
- Throughput measurement (bandwidth)
- Latency measurement (round-trip time)
- Scalability testing (increasing load)
- Resource utilization (CPU, memory, DMA buffers)

## Cornelis-Specific Patterns

### Omni-Path Architecture
- Host Fabric Interface (HFI) connects host to fabric
- Packet-based communication over high-speed serial links
- PSM2 (Performance Scaled Messaging) for MPI
- Verbs/RDMA for kernel-bypass data transfer

### Fabric Manager Integration
- FM discovers and manages fabric topology
- Subnet Manager (SM) assigns addresses and routes
- Performance Manager (PM) collects counters
- Health monitoring and fault detection

### Build System
- Firmware: typically cross-compiled for embedded target
- Drivers: built against kernel headers (DKMS for distribution)
- Tools: standard autotools or CMake
- Packaging: RPM/DEB for Linux distributions
