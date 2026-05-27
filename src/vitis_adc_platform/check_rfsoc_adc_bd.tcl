# Batch checker for the RFSoC ADC block design.
#
# Run from any directory:
#   vivado -mode batch -source /path/to/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl
#   vivado -mode batch -source /path/to/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl \
#     -tclargs --hardware_tcl /path/to/rfsoc_adc_hardware.tcl
#
# Or run after opening an existing project:
#   source /path/to/src/vitis_adc_platform/check_rfsoc_adc_bd.tcl

set script_dir [file dirname [file normalize [info script]]]
set hardware_tcl [file join $script_dir rfsoc_adc_hardware.tcl]
set start_dir [pwd]

if {[info exists ::argv]} {
  for {set i 0} {$i < $::argc} {incr i} {
    set option [lindex $::argv $i]
    switch -- $option {
      "--hardware_tcl" {
        incr i
        set hardware_tcl [file normalize [lindex $::argv $i]]
      }
      default {
        puts "ERROR: Unknown option '$option'"
        puts "Usage: check_rfsoc_adc_bd.tcl -tclargs \[--hardware_tcl <path>\]"
        exit 1
      }
    }
  }
}

proc fail {msg} {
  puts "ERROR: $msg"
  exit 1
}

proc print_prop {obj prop} {
  if {[catch {get_property $prop $obj} value]} {
    puts "$prop = <missing>"
    return ""
  }
  puts "$prop = $value"
  return $value
}

if {[llength [get_projects -quiet]] == 0} {
  if {![file exists $hardware_tcl]} {
    fail "Cannot find $hardware_tcl"
  }

  set ::origin_dir_loc [file dirname $hardware_tcl]
  set check_dir [file normalize [file join $start_dir "rfsoc_adc_bd_check_[clock seconds]"]]
  file mkdir $check_dir
  cd $check_dir
  puts "INFO: Creating temporary check project under $check_dir"
  source $hardware_tcl
}

set bd_files [get_files -quiet *system.bd]
if {[llength $bd_files] == 0} {
  fail "system.bd was not found in the current project"
}

if {[catch {current_bd_design} current_bd] || $current_bd eq ""} {
  open_bd_design -quiet [lindex $bd_files 0]
}

set rfdc [get_bd_cells -quiet /usp_rf_data_converter_0]
if {[llength $rfdc] == 0} {
  fail "RFDC cell /usp_rf_data_converter_0 was not found"
}

puts "current BD = [current_bd_design]"
set slice02 [print_prop $rfdc CONFIG.ADC_Slice02_Enable]
set decim00 [print_prop $rfdc CONFIG.ADC_Decimation_Mode00]
set decim02 [print_prop $rfdc CONFIG.ADC_Decimation_Mode02]
set outclk [print_prop $rfdc CONFIG.ADC0_Outclk_Freq]
set sampling_rate [print_prop $rfdc CONFIG.ADC0_Sampling_Rate]
set width02 [print_prop $rfdc CONFIG.ADC_Data_Width02]
set type02 [print_prop $rfdc CONFIG.ADC_Data_Type02]
set axis_ports [print_prop $rfdc PFM.AXIS_PORT]

set vin0_23_ports [llength [get_bd_intf_ports -quiet vin0_23]]
set vin0_23_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/vin0_23]]
set m02_axis_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/m02_axis]]
set pfm_m00_tag ""
set pfm_m02_tag ""

if {$axis_ports ne ""} {
  if {[catch {
    if {[dict exists $axis_ports m00_axis]} {
      set pfm_m00_tag [dict get [dict get $axis_ports m00_axis] sptag]
    }
    if {[dict exists $axis_ports m02_axis]} {
      set pfm_m02_tag [dict get [dict get $axis_ports m02_axis] sptag]
    }
  } pfm_err]} {
    puts "ERROR: Could not parse PFM.AXIS_PORT: $pfm_err"
  }
}

puts "vin0_23 external port count = $vin0_23_ports"
puts "vin0_23 RFDC pin count = $vin0_23_pins"
puts "m02_axis RFDC pin count = $m02_axis_pins"
puts "PFM m00_axis sptag = $pfm_m00_tag"
puts "PFM m02_axis sptag = $pfm_m02_tag"

set failures 0
if {$slice02 ne "true"} {
  puts "ERROR: Expected CONFIG.ADC_Slice02_Enable to be true"
  incr failures
}
if {$decim00 ne "8"} {
  puts "ERROR: Expected CONFIG.ADC_Decimation_Mode00 to be 8"
  incr failures
}
if {$decim02 ne "8"} {
  puts "ERROR: Expected CONFIG.ADC_Decimation_Mode02 to be 8"
  incr failures
}
if {$width02 ne "8"} {
  puts "ERROR: Expected CONFIG.ADC_Data_Width02 to be 8"
  incr failures
}
if {$type02 ne "0"} {
  puts "ERROR: Expected CONFIG.ADC_Data_Type02 to be 0"
  incr failures
}
if {$vin0_23_ports != 1} {
  puts "ERROR: Expected one external vin0_23 port"
  incr failures
}
if {$vin0_23_pins != 1} {
  puts "ERROR: Expected one RFDC vin0_23 pin"
  incr failures
}
if {$m02_axis_pins != 1} {
  puts "ERROR: Expected one RFDC m02_axis pin"
  incr failures
}
if {$pfm_m00_tag ne "RFDC_DATA_AXIS"} {
  puts "ERROR: Expected m00_axis PFM sptag to be RFDC_DATA_AXIS"
  incr failures
}
if {$pfm_m02_tag ne "RFDC_TRIG_AXIS"} {
  puts "ERROR: Expected m02_axis PFM sptag to be RFDC_TRIG_AXIS"
  incr failures
}

if {[catch {validate_bd_design} validate_msg validate_opts]} {
  puts "ERROR: validate_bd_design failed:"
  puts $validate_msg
  incr failures
} else {
  puts "validate_bd_design completed"
}

if {$failures != 0} {
  puts "CHECK FAILED: $failures issue(s)"
  exit 1
}

puts "CHECK PASSED: ADC slice 02, vin0_23, and exported RFDC streams are present"
exit 0
