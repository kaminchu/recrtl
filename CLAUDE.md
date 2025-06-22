# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python CLI tool for receiving Japanese One-Seg (1seg) digital TV broadcasts using affordable RTL2832-based USB tuners. The tool outputs MPEG-TS streams to stdout for pipeline integration with ffmpeg and media players.

## Key Architecture Components

### Signal Processing Pipeline
The application follows a multi-stage signal processing pipeline:
1. **RTL-SDR Interface** (`src/rtl_interface.py`) - RTL2832 USB tuner control
2. **ISDB-T Decoder** (`src/isdb_decoder.py`) - OFDM demodulation and Mode 3 (13-segment) processing
3. **One-Seg Parser** (`src/oneseg_parser.py`) - Transport Stream analysis and PID extraction
4. **TS Output** (`src/ts_output.py`) - MPEG-TS stream output to stdout

### Technical Specifications
- **Target Standard**: ISDB-T Mode 3 (Japanese digital terrestrial TV)
- **One-Seg Focus**: Central segment (segment 0) extraction from 13-segment structure
- **Frequency Range**: 470-770MHz (UHF channels 13-62)
- **Output Format**: MPEG-2 Transport Stream via stdout
- **Key Libraries**: pyrtlsdr, numpy, scipy

## Development Commands

### Setup and Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Install package in development mode  
pip install -e .
```

### Running the Tool
```bash
# Basic usage - receive channel 13 and pipe to ffplay
python oneseg.py -c 13 | ffplay -

# List available RTL-SDR devices
python oneseg.py --list-devices

# Verbose output with signal strength info
python oneseg.py -c 13 -v | ffplay -
```

### Testing
```bash
# Run unit tests
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_rtl_interface.py -v
```

## Task Management System

This project uses a structured task management approach:

### Core Documents
- **SPEC.md**: Technical specifications and requirements (Japanese)
- **TASK.md**: Detailed task breakdown with technical implementation details (Japanese)  
- **TODO.md**: Progress tracking with checkboxes and status updates (Japanese)

### Development Workflow
1. **Follow TODO.md**: Check current task status and next priorities
2. **Reference TASK.md**: Get detailed technical requirements for implementation
3. **Update Progress**: Mark tasks complete in TODO.md after finishing
4. **Commit Per Task**: Commit changes after each completed task
5. **Update TASK.md**: Modify task details when requirements change

### Task Phases
- **Phase 1**: Project foundation (directory structure, CLI setup)
- **Phase 2**: RTL-SDR control infrastructure  
- **Phase 3**: Signal processing (OFDM, ISDB-T Mode 3)
- **Phase 4**: One-Seg processing (error correction, TS parsing)
- **Phase 5**: Integration and testing
- **Phase 6**: Optimization and completion

## Communication Guidelines

- Basic interactions and comments in documents and code should be in Japanese
- However, this CLAUDE.md file should be written entirely in English
- Update TASK.md each time a task is completed
- As work progresses, requirements may change - ask questions and reflect changes in TASK.md accordingly

## Technical Challenges

### Real-time Processing Constraints
Python performance limitations for real-time signal processing may require optimization through:
- Efficient numpy operations
- Minimal memory allocations in processing loops
- Potential C extensions for critical paths

### ISDB-T Complexity
The Japanese ISDB-T standard involves sophisticated signal processing:
- OFDM with 1405 carriers in Mode 3
- Reed-Solomon and convolutional error correction
- Complex interleaving schemes
- Multiple modulation schemes (QPSK/16QAM/64QAM)

### Hardware Variability
RTL-SDR dongles have significant individual differences in:
- Frequency accuracy and drift
- Gain characteristics  
- Noise performance
- Temperature stability

## Project Structure

```
oneseg/
├── SPEC.md          # Technical specifications (Japanese)
├── TASK.md          # Implementation task breakdown (Japanese)  
├── TODO.md          # Progress tracking (Japanese)
├── CLAUDE.md        # This file (English)
├── requirements.txt # Python dependencies
├── setup.py         # Package configuration
├── oneseg.py        # Main CLI script
├── src/             # Core implementation modules
│   ├── rtl_interface.py  # RTL-SDR hardware control
│   ├── isdb_decoder.py   # ISDB-T signal processing
│   ├── oneseg_parser.py  # Transport stream analysis
│   └── ts_output.py      # MPEG-TS output handling
└── tests/           # Unit tests
    └── test_*.py    # Test modules
```