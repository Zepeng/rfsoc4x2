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
set hardware_tcl_explicit 0
set start_dir [pwd]

if {[info exists ::argv]} {
  for {set i 0} {$i < $::argc} {incr i} {
    set option [lindex $::argv $i]
    switch -- $option {
      "--hardware_tcl" {
        incr i
        set hardware_tcl [file normalize [lindex $::argv $i]]
        set hardware_tcl_explicit 1
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

set open_projects [get_projects -quiet]
if {[llength $open_projects] == 0} {
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
} else {
  if {$hardware_tcl_explicit} {
    fail "--hardware_tcl cannot be checked while a project is already open; close_project and rerun the batch checker"
  }
  set project_name [get_property NAME [current_project]]
  set project_dir "<unknown>"
  catch {set project_dir [get_property DIRECTORY [current_project]]}
  puts "INFO: Inspecting already-open project '$project_name' at '$project_dir'"
  puts "INFO: The hardware Tcl was not sourced for this check"
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
set pps [get_bd_cells -quiet /pps_trigger_axis_0]
if {[llength $pps] == 0} {
  fail "PPS trigger adapter cell /pps_trigger_axis_0 was not found"
}
set pps_ila [get_bd_cells -quiet /ila_pps_trigger]
if {[llength $pps_ila] == 0} {
  fail "PPS ILA cell /ila_pps_trigger was not found"
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
set rfdc_clocks [print_prop $rfdc PFM.CLOCK]
set axis_ports [print_prop $rfdc PFM.AXIS_PORT]
set pps_axis_ports [print_prop $pps PFM.AXIS_PORT]

set irig_ports [llength [get_bd_ports -quiet IRIG_TRIG_OUT]]
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
set m0_axis_aclk_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /usp_rf_data_converter_0/m0_axis_aclk]]]
set m2_axis_aclk_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /usp_rf_data_converter_0/m2_axis_aclk]]]
set pps_aclk_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /pps_trigger_axis_0/aclk]]]
set pps_aresetn_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /pps_trigger_axis_0/aresetn]]]
set pps_in_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /pps_trigger_axis_0/pps_in]]]
set pps_in_ports [get_bd_ports -quiet -of_objects [get_bd_nets -of_objects [get_bd_pins /pps_trigger_axis_0/pps_in]]]
set pps_ila_clk_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /ila_pps_trigger/clk]]]
set pps_ila_probe0_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /ila_pps_trigger/probe0]]]
set pps_ila_probe1_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /ila_pps_trigger/probe1]]]
set pps_ila_probe2_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /ila_pps_trigger/probe2]]]
set pps_ila_probe3_net [get_property NAME [get_bd_nets -of_objects [get_bd_pins /ila_pps_trigger/probe3]]]
set pps_ila_probe4_pins [llength [get_bd_pins -quiet /ila_pps_trigger/probe4]]
set pps_ila_probes [print_prop $pps_ila CONFIG.C_NUM_OF_PROBES]
set pfm_m00_tag ""
set pfm_m02_tag ""
set pfm_m20_tag ""
set pfm_m22_tag ""
set pfm_pps_tag ""
set pfm_clk_adc0_id ""
set pfm_clk_adc0_status ""
set pfm_clk_adc0_freq ""
set pfm_clk_adc2_id ""
set pfm_clk_adc2_status ""
set pfm_clk_adc2_freq ""

if {$rfdc_clocks ne ""} {
  if {[catch {
    if {[dict exists $rfdc_clocks clk_adc0]} {
      set pfm_clk_adc0_id [dict get [dict get $rfdc_clocks clk_adc0] id]
      set pfm_clk_adc0_status [dict get [dict get $rfdc_clocks clk_adc0] status]
      set pfm_clk_adc0_freq [dict get [dict get $rfdc_clocks clk_adc0] freq_hz]
    }
    if {[dict exists $rfdc_clocks clk_adc2]} {
      set pfm_clk_adc2_id [dict get [dict get $rfdc_clocks clk_adc2] id]
      set pfm_clk_adc2_status [dict get [dict get $rfdc_clocks clk_adc2] status]
      set pfm_clk_adc2_freq [dict get [dict get $rfdc_clocks clk_adc2] freq_hz]
    }
  } pfm_err]} {
    puts "ERROR: Could not parse PFM.CLOCK: $pfm_err"
  }
}

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

if {$pps_axis_ports ne ""} {
  if {[catch {
    if {[dict exists $pps_axis_ports m_axis]} {
      set pfm_pps_tag [dict get [dict get $pps_axis_ports m_axis] sptag]
    }
  } pfm_err]} {
    puts "ERROR: Could not parse PPS PFM.AXIS_PORT: $pfm_err"
  }
}

puts "IRIG_TRIG_OUT external port count = $irig_ports"
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
puts "m0_axis_aclk net = $m0_axis_aclk_net"
puts "m2_axis_aclk net = $m2_axis_aclk_net"
puts "pps_trigger_axis_0/aclk net = $pps_aclk_net"
puts "pps_trigger_axis_0/aresetn net = $pps_aresetn_net"
puts "pps_trigger_axis_0/pps_in net = $pps_in_net"
puts "pps_trigger_axis_0/pps_in external port = $pps_in_ports"
puts "ila_pps_trigger/clk net = $pps_ila_clk_net"
puts "ila_pps_trigger probe count = $pps_ila_probes"
puts "ila_pps_trigger/probe0 net = $pps_ila_probe0_net"
puts "ila_pps_trigger/probe1 net = $pps_ila_probe1_net"
puts "ila_pps_trigger/probe2 net = $pps_ila_probe2_net"
puts "ila_pps_trigger/probe3 net = $pps_ila_probe3_net"
puts "ila_pps_trigger/probe4 pin count = $pps_ila_probe4_pins"
puts "PFM m00_axis sptag = $pfm_m00_tag"
puts "PFM m02_axis sptag = $pfm_m02_tag"
puts "PFM m20_axis sptag = $pfm_m20_tag"
puts "PFM m22_axis sptag = $pfm_m22_tag"
puts "PFM PPS m_axis sptag = $pfm_pps_tag"
puts "PFM clk_adc0 = id $pfm_clk_adc0_id, status $pfm_clk_adc0_status, freq_hz $pfm_clk_adc0_freq"
puts "PFM clk_adc2 = id $pfm_clk_adc2_id, status $pfm_clk_adc2_status, freq_hz $pfm_clk_adc2_freq"

set failures 0
if {$irig_ports != 1} {
  puts "ERROR: Expected one external IRIG_TRIG_OUT port"
  incr failures
}
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
  CONFIG.ADC_Decimation_Mode00 $decim00 8 \
  CONFIG.ADC_Decimation_Mode02 $decim02 8 \
  CONFIG.ADC_Decimation_Mode20 $decim20 8 \
  CONFIG.ADC_Decimation_Mode22 $decim22 8 \
  CONFIG.ADC0_Outclk_Freq $outclk0 307.200 \
  CONFIG.ADC2_Outclk_Freq $outclk2 307.200 \
  CONFIG.ADC0_Sampling_Rate $sampling_rate0 4.9152 \
  CONFIG.ADC2_Sampling_Rate $sampling_rate2 4.9152 \
  CONFIG.ADC_Data_Width00 $width00 2 \
  CONFIG.ADC_Data_Width02 $width02 2 \
  CONFIG.ADC_Data_Width20 $width20 2 \
  CONFIG.ADC_Data_Width22 $width22 2 \
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
if {$m0_axis_aclk_net ne "usp_rf_data_converter_0_clk_adc0"} {
  puts "ERROR: Expected m0_axis_aclk to use usp_rf_data_converter_0_clk_adc0"
  incr failures
}
if {$m2_axis_aclk_net ne "usp_rf_data_converter_0_clk_adc0"} {
  puts "ERROR: Expected m2_axis_aclk to use common stream clock usp_rf_data_converter_0_clk_adc0"
  incr failures
}
if {$pps_aclk_net ne "usp_rf_data_converter_0_clk_adc0"} {
  puts "ERROR: Expected PPS trigger adapter to use common stream clock usp_rf_data_converter_0_clk_adc0"
  incr failures
}
if {$pps_ila_clk_net ne "usp_rf_data_converter_0_clk_adc0"} {
  puts "ERROR: Expected PPS ILA to use common stream clock usp_rf_data_converter_0_clk_adc0"
  incr failures
}
if {$pps_aresetn_net ne "proc_sys_reset_clk_adc0_peripheral_aresetn"} {
  puts "ERROR: Expected PPS trigger adapter reset to use proc_sys_reset_clk_adc0_peripheral_aresetn"
  incr failures
}
if {[llength $pps_in_ports] != 1 || [get_property NAME [lindex $pps_in_ports 0]] ne "IRIG_TRIG_OUT"} {
  puts "ERROR: Expected PPS trigger adapter input to be driven by IRIG_TRIG_OUT"
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
if {$pfm_pps_tag ne "PPS_TRIG_AXIS"} {
  puts "ERROR: Expected PPS m_axis PFM sptag to be PPS_TRIG_AXIS"
  incr failures
}
if {$pps_ila_probes ne "4"} {
  puts "ERROR: Expected ila_pps_trigger to have 4 probes"
  incr failures
}
foreach {probe_name actual_net expected_net} [list \
  probe0 $pps_ila_probe0_net pps_trigger_sync_level \
  probe1 $pps_ila_probe1_net pps_trigger_axis_level \
  probe2 $pps_ila_probe2_net pps_trigger_axis_valid \
  probe3 $pps_ila_probe3_net proc_sys_reset_clk_adc0_peripheral_aresetn \
] {
  if {$actual_net ne $expected_net} {
    puts "ERROR: Expected ila_pps_trigger/$probe_name to use $expected_net, got $actual_net"
    incr failures
  }
}
if {$pps_ila_probe4_pins != 0} {
  puts "ERROR: Expected ila_pps_trigger/probe4 to be absent"
  incr failures
}
foreach {name value expected} [list \
  {clk_adc0 PFM id} $pfm_clk_adc0_id 3 \
  {clk_adc0 PFM status} $pfm_clk_adc0_status fixed \
  {clk_adc0 PFM freq_hz} $pfm_clk_adc0_freq 307200000 \
  {clk_adc2 PFM id} $pfm_clk_adc2_id 4 \
  {clk_adc2 PFM status} $pfm_clk_adc2_status fixed \
  {clk_adc2 PFM freq_hz} $pfm_clk_adc2_freq 307200000 \
] {
  if {$value ne $expected} {
    puts "ERROR: Expected $name to be $expected"
    incr failures
  }
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

puts "CHECK PASSED: four 614.4 MS/s ADC streams plus PPS_TRIG_AXIS and PPS ILA use common clk_adc0"
exit 0
