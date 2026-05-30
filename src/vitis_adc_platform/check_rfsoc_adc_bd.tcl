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
  set saved_argv $::argv
  set saved_argc $::argc
  set ::argv {}
  set ::argc 0
  set source_rc [catch {source $hardware_tcl} source_msg source_opts]
  set ::argv $saved_argv
  set ::argc $saved_argc
  if {$source_rc != 0} {
    return -options $source_opts $source_msg
  }
}

set bd_files [get_files -quiet *system.bd]
if {[llength $bd_files] == 0} {
  fail "system.bd was not found in the current project"
}

open_bd_design -quiet [lindex $bd_files 0]

set rfdc [get_bd_cells -quiet /usp_rf_data_converter_0]
if {[llength $rfdc] == 0} {
  fail "RFDC cell /usp_rf_data_converter_0 was not found"
}

puts "current BD = [current_bd_design]"
set slice00 [print_prop $rfdc CONFIG.ADC_Slice00_Enable]
set slice02 [print_prop $rfdc CONFIG.ADC_Slice02_Enable]
set slice20 [print_prop $rfdc CONFIG.ADC_Slice20_Enable]
set slice22 [print_prop $rfdc CONFIG.ADC_Slice22_Enable]
set decim00 [print_prop $rfdc CONFIG.ADC_Decimation_Mode00]
set decim02 [print_prop $rfdc CONFIG.ADC_Decimation_Mode02]
set decim20 [print_prop $rfdc CONFIG.ADC_Decimation_Mode20]
set decim22 [print_prop $rfdc CONFIG.ADC_Decimation_Mode22]
set outclk0 [print_prop $rfdc CONFIG.ADC0_Outclk_Freq]
set outclk2 [print_prop $rfdc CONFIG.ADC2_Outclk_Freq]
set sampling_rate0 [print_prop $rfdc CONFIG.ADC0_Sampling_Rate]
set sampling_rate2 [print_prop $rfdc CONFIG.ADC2_Sampling_Rate]
set width00 [print_prop $rfdc CONFIG.ADC_Data_Width00]
set width02 [print_prop $rfdc CONFIG.ADC_Data_Width02]
set width20 [print_prop $rfdc CONFIG.ADC_Data_Width20]
set width22 [print_prop $rfdc CONFIG.ADC_Data_Width22]
set type00 [print_prop $rfdc CONFIG.ADC_Data_Type00]
set type02 [print_prop $rfdc CONFIG.ADC_Data_Type02]
set type20 [print_prop $rfdc CONFIG.ADC_Data_Type20]
set type22 [print_prop $rfdc CONFIG.ADC_Data_Type22]
set axis_ports [print_prop $rfdc PFM.AXIS_PORT]

set vin0_01_ports [llength [get_bd_intf_ports -quiet vin0_01]]
set vin0_23_ports [llength [get_bd_intf_ports -quiet vin0_23]]
set vin2_01_ports [llength [get_bd_intf_ports -quiet vin2_01]]
set vin2_23_ports [llength [get_bd_intf_ports -quiet vin2_23]]
set vin0_01_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/vin0_01]]
set vin0_23_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/vin0_23]]
set vin2_01_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/vin2_01]]
set vin2_23_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/vin2_23]]
set m00_axis_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/m00_axis]]
set m02_axis_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/m02_axis]]
set m20_axis_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/m20_axis]]
set m22_axis_pins [llength [get_bd_intf_pins -quiet /usp_rf_data_converter_0/m22_axis]]
set pfm_m00_tag ""
set pfm_m02_tag ""
set pfm_m20_tag ""
set pfm_m22_tag ""

if {$axis_ports ne ""} {
  if {[catch {
    if {[dict exists $axis_ports m00_axis]} {
      set pfm_m00_tag [dict get [dict get $axis_ports m00_axis] sptag]
    }
    if {[dict exists $axis_ports m02_axis]} {
      set pfm_m02_tag [dict get [dict get $axis_ports m02_axis] sptag]
    }
    if {[dict exists $axis_ports m20_axis]} {
      set pfm_m20_tag [dict get [dict get $axis_ports m20_axis] sptag]
    }
    if {[dict exists $axis_ports m22_axis]} {
      set pfm_m22_tag [dict get [dict get $axis_ports m22_axis] sptag]
    }
  } pfm_err]} {
    puts "ERROR: Could not parse PFM.AXIS_PORT: $pfm_err"
  }
}

puts "vin0_01 external port count = $vin0_01_ports"
puts "vin0_23 external port count = $vin0_23_ports"
puts "vin2_01 external port count = $vin2_01_ports"
puts "vin2_23 external port count = $vin2_23_ports"
puts "vin0_01 RFDC pin count = $vin0_01_pins"
puts "vin0_23 RFDC pin count = $vin0_23_pins"
puts "vin2_01 RFDC pin count = $vin2_01_pins"
puts "vin2_23 RFDC pin count = $vin2_23_pins"
puts "m00_axis RFDC pin count = $m00_axis_pins"
puts "m02_axis RFDC pin count = $m02_axis_pins"
puts "m20_axis RFDC pin count = $m20_axis_pins"
puts "m22_axis RFDC pin count = $m22_axis_pins"
puts "PFM m00_axis sptag = $pfm_m00_tag"
puts "PFM m02_axis sptag = $pfm_m02_tag"
puts "PFM m20_axis sptag = $pfm_m20_tag"
puts "PFM m22_axis sptag = $pfm_m22_tag"

set failures 0
if {$slice00 ne "true"} {
  puts "ERROR: Expected CONFIG.ADC_Slice00_Enable to be true"
  incr failures
}
if {$slice02 ne "true"} {
  puts "ERROR: Expected CONFIG.ADC_Slice02_Enable to be true"
  incr failures
}
if {$slice20 ne "true"} {
  puts "ERROR: Expected CONFIG.ADC_Slice20_Enable to be true"
  incr failures
}
if {$slice22 ne "true"} {
  puts "ERROR: Expected CONFIG.ADC_Slice22_Enable to be true"
  incr failures
}
foreach {name value expected} [list \
  CONFIG.ADC_Decimation_Mode00 $decim00 2 \
  CONFIG.ADC_Decimation_Mode02 $decim02 2 \
  CONFIG.ADC_Decimation_Mode20 $decim20 2 \
  CONFIG.ADC_Decimation_Mode22 $decim22 2 \
  CONFIG.ADC0_Outclk_Freq $outclk0 307.200 \
  CONFIG.ADC2_Outclk_Freq $outclk2 307.200 \
  CONFIG.ADC0_Sampling_Rate $sampling_rate0 4.9152 \
  CONFIG.ADC2_Sampling_Rate $sampling_rate2 4.9152 \
  CONFIG.ADC_Data_Width00 $width00 8 \
  CONFIG.ADC_Data_Width02 $width02 8 \
  CONFIG.ADC_Data_Width20 $width20 8 \
  CONFIG.ADC_Data_Width22 $width22 8 \
  CONFIG.ADC_Data_Type00 $type00 0 \
  CONFIG.ADC_Data_Type02 $type02 0 \
  CONFIG.ADC_Data_Type20 $type20 0 \
  CONFIG.ADC_Data_Type22 $type22 0 \
] {
  if {$value ne $expected} {
    puts "ERROR: Expected $name to be $expected"
    incr failures
  }
}
if {$vin0_01_ports != 1} {
  puts "ERROR: Expected one external vin0_01 port"
  incr failures
}
if {$vin0_23_ports != 1} {
  puts "ERROR: Expected one external vin0_23 port"
  incr failures
}
if {$vin2_01_ports != 1} {
  puts "ERROR: Expected one external vin2_01 port"
  incr failures
}
if {$vin2_23_ports != 1} {
  puts "ERROR: Expected one external vin2_23 port"
  incr failures
}
if {$vin0_01_pins != 1} {
  puts "ERROR: Expected one RFDC vin0_01 pin"
  incr failures
}
if {$vin0_23_pins != 1} {
  puts "ERROR: Expected one RFDC vin0_23 pin"
  incr failures
}
if {$vin2_01_pins != 1} {
  puts "ERROR: Expected one RFDC vin2_01 pin"
  incr failures
}
if {$vin2_23_pins != 1} {
  puts "ERROR: Expected one RFDC vin2_23 pin"
  incr failures
}
if {$m00_axis_pins != 1} {
  puts "ERROR: Expected one RFDC m00_axis pin"
  incr failures
}
if {$m02_axis_pins != 1} {
  puts "ERROR: Expected one RFDC m02_axis pin"
  incr failures
}
if {$m20_axis_pins != 1} {
  puts "ERROR: Expected one RFDC m20_axis pin"
  incr failures
}
if {$m22_axis_pins != 1} {
  puts "ERROR: Expected one RFDC m22_axis pin"
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
if {$pfm_m20_tag ne "RFDC_ADC_B_AXIS"} {
  puts "ERROR: Expected m20_axis PFM sptag to be RFDC_ADC_B_AXIS"
  incr failures
}
if {$pfm_m22_tag ne "RFDC_ADC_A_AXIS"} {
  puts "ERROR: Expected m22_axis PFM sptag to be RFDC_ADC_A_AXIS"
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

puts "CHECK PASSED: tile 0/tile 2 real ADC streams and exported RFDC tags are present"
exit 0
