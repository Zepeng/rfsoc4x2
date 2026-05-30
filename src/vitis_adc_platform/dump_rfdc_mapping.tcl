# Dump RFDC ADC stream/export mapping from a Vivado block design.
#
# Run from any directory:
#   vivado -mode batch -source /path/to/src/vitis_adc_platform/dump_rfdc_mapping.tcl
#   vivado -mode batch -source /path/to/src/vitis_adc_platform/dump_rfdc_mapping.tcl \
#     -tclargs --hardware_tcl /path/to/rfsoc_adc_hardware.tcl
#
# Or run after opening an existing Vivado project:
#   source /path/to/src/vitis_adc_platform/dump_rfdc_mapping.tcl

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
        puts "Usage: dump_rfdc_mapping.tcl -tclargs \[--hardware_tcl <path>\]"
        exit 1
      }
    }
  }
}

proc fail {msg} {
  puts "ERROR: $msg"
  exit 1
}

proc prop_or_missing {obj prop} {
  if {[catch {get_property $prop $obj} value]} {
    return "<missing>"
  }
  if {$value eq ""} {
    return "<empty>"
  }
  return $value
}

proc print_pin_net {pin_name} {
  set pin [get_bd_intf_pins -quiet $pin_name]
  if {[llength $pin] == 0} {
    puts [format "%-45s missing" $pin_name]
    return
  }
  set net [get_bd_intf_nets -quiet -of_objects $pin]
  if {[llength $net] == 0} {
    puts [format "%-45s present, no net" $pin_name]
    return
  }
  puts [format "%-45s net=%s" $pin_name $net]
}

proc print_port_net {port_name} {
  set port [get_bd_intf_ports -quiet $port_name]
  if {[llength $port] == 0} {
    puts [format "%-20s missing" $port_name]
    return
  }
  set net [get_bd_intf_nets -quiet -of_objects $port]
  puts [format "%-20s net=%s board=%s" \
        $port_name $net [prop_or_missing $port BOARD_INTERFACE]]
}

if {[llength [get_projects -quiet]] == 0} {
  if {![file exists $hardware_tcl]} {
    fail "Cannot find $hardware_tcl"
  }

  set ::origin_dir_loc [file dirname $hardware_tcl]
  set dump_dir [file normalize [file join $start_dir "rfsoc_adc_mapping_dump_[clock seconds]"]]
  file mkdir $dump_dir
  cd $dump_dir
  puts "INFO: Creating temporary dump project under $dump_dir"
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
puts "\nExternal RFDC analog input ports:"
foreach port_name {vin0_01 vin0_23 vin1_01 vin1_23 vin2_01 vin2_23 vin3_01 vin3_23} {
  print_port_net $port_name
}

puts "\nRFDC AXIS output pins:"
foreach pin_name {
  /usp_rf_data_converter_0/m00_axis
  /usp_rf_data_converter_0/m01_axis
  /usp_rf_data_converter_0/m02_axis
  /usp_rf_data_converter_0/m03_axis
  /usp_rf_data_converter_0/m10_axis
  /usp_rf_data_converter_0/m11_axis
  /usp_rf_data_converter_0/m12_axis
  /usp_rf_data_converter_0/m13_axis
  /usp_rf_data_converter_0/m20_axis
  /usp_rf_data_converter_0/m21_axis
  /usp_rf_data_converter_0/m22_axis
  /usp_rf_data_converter_0/m23_axis
  /usp_rf_data_converter_0/m30_axis
  /usp_rf_data_converter_0/m31_axis
  /usp_rf_data_converter_0/m32_axis
  /usp_rf_data_converter_0/m33_axis
} {
  print_pin_net $pin_name
}

puts "\nPlatform AXIS export tags:"
puts "PFM.AXIS_PORT = [prop_or_missing $rfdc PFM.AXIS_PORT]"

puts "\nRFDC ADC properties relevant to exported real streams:"
foreach prop {
  CONFIG.ADC0_Sampling_Rate
  CONFIG.ADC0_Outclk_Freq
  CONFIG.ADC0_Refclk_Freq
  CONFIG.ADC2_Sampling_Rate
  CONFIG.ADC2_Outclk_Freq
  CONFIG.ADC2_Refclk_Freq
  CONFIG.ADC_Slice00_Enable
  CONFIG.ADC_Slice02_Enable
  CONFIG.ADC_Slice20_Enable
  CONFIG.ADC_Slice22_Enable
  CONFIG.ADC_Data_Type00
  CONFIG.ADC_Data_Type02
  CONFIG.ADC_Data_Type20
  CONFIG.ADC_Data_Type22
  CONFIG.ADC_Data_Width00
  CONFIG.ADC_Data_Width02
  CONFIG.ADC_Data_Width20
  CONFIG.ADC_Data_Width22
  CONFIG.ADC_Decimation_Mode00
  CONFIG.ADC_Decimation_Mode02
  CONFIG.ADC_Decimation_Mode20
  CONFIG.ADC_Decimation_Mode22
} {
  puts "$prop = [prop_or_missing $rfdc $prop]"
}

puts "\nRFDC cell summary:"
puts "VLNV = [get_property VLNV $rfdc]"
puts "CONFIG.ADC0_Sampling_Rate = [prop_or_missing $rfdc CONFIG.ADC0_Sampling_Rate]"
puts "CONFIG.ADC0_Outclk_Freq = [prop_or_missing $rfdc CONFIG.ADC0_Outclk_Freq]"
puts "CONFIG.ADC0_Refclk_Freq = [prop_or_missing $rfdc CONFIG.ADC0_Refclk_Freq]"
puts "CONFIG.ADC2_Sampling_Rate = [prop_or_missing $rfdc CONFIG.ADC2_Sampling_Rate]"
puts "CONFIG.ADC2_Outclk_Freq = [prop_or_missing $rfdc CONFIG.ADC2_Outclk_Freq]"
puts "CONFIG.ADC2_Refclk_Freq = [prop_or_missing $rfdc CONFIG.ADC2_Refclk_Freq]"

exit 0
