# Vivado 2025.2 migration driver for the RFSoC4x2 ADC platform.
#
# This script deliberately keeps rfsoc_adc_hardware_2023_2_1.tcl unchanged as
# the known-good design description. It adapts generated run-flow names, the
# board-repository path, incompatible metadata, and the legacy PPS ILA AXIS
# ready probe before sourcing that design in Vivado 2025.2.
#
# Example:
#   vivado -mode batch \
#     -source rfsoc_adc_hardware_2025_2.tcl \
#     -tclargs \
#       --board_repo /path/to/RFSoC4x2-BSP \
#       --output_dir /path/to/build/vivado_2025_2 \
#       --export_xsa /path/to/build/rfsoc_adc_hardware_2025_2.xsa
#
# Add --build to run synthesis, implementation, and write_bitstream.

namespace eval ::rfsoc_adc_2025_2 {
  variable expected_version "2025.2"
  variable script_dir [file dirname [file normalize [info script]]]
  variable board_repo_dir ""
}

proc ::rfsoc_adc_2025_2::usage {} {
  puts "Vivado 2025.2 RFSoC4x2 ADC platform migration driver"
  puts ""
  puts "Options:"
  puts "  --board_repo <path>       RFSoC4x2-BSP root or board_files directory."
  puts "                              May also be set with RFSOC4X2_BOARD_REPO."
  puts "  --output_dir <path>       Parent directory for the Vivado project."
  puts "                              Default: <cwd>/build/vivado_2025_2"
  puts "  --project_name <name>     Vivado project name."
  puts "                              Default: rfsoc_adc_hardware_2025_2"
  puts "  --export_xsa <path>       Write a validated extensible hardware XSA."
  puts "  --export_hw_emu_xsa <path>"
  puts "                            Also write a hardware-emulation XSA."
  puts "  --build                   Run synthesis through write_bitstream."
  puts "  --jobs <count>            Parallel jobs for implementation. Default: 8"
  puts "  --help                    Show this help."
}

proc ::rfsoc_adc_2025_2::fail {message} {
  return -code error "Vivado 2025.2 port: $message"
}

proc ::rfsoc_adc_2025_2::resolve_board_repo {path} {
  set normalized [file normalize $path]
  foreach candidate [list $normalized [file join $normalized board_files]] {
    set board_xml [file join $candidate rfsoc4x2 1.0 board.xml]
    if {[file isfile $board_xml]} {
      return [file normalize $candidate]
    }
  }

  fail "cannot find rfsoc4x2/1.0/board.xml under '$normalized' or its board_files subdirectory"
}

proc ::rfsoc_adc_2025_2::require_arg {option index} {
  if {$index >= $::argc} {
    fail "$option requires a value"
  }
  return [lindex $::argv $index]
}

proc ::rfsoc_adc_2025_2::run_to_completion {run_name jobs args} {
  set run [get_runs -quiet $run_name]
  if {[llength $run] != 1} {
    fail "expected one Vivado run named '$run_name'"
  }

  if {[llength $args] == 0} {
    launch_runs $run_name -jobs $jobs
  } else {
    launch_runs $run_name -jobs $jobs {*}$args
  }
  wait_on_run $run_name

  set status [get_property STATUS $run]
  puts "INFO: $run_name status: $status"
  if {![string match "*Complete*" $status]} {
    fail "$run_name did not complete successfully: $status"
  }
}

set board_repo_arg ""
if {[info exists ::env(RFSOC4X2_BOARD_REPO)]} {
  set board_repo_arg $::env(RFSOC4X2_BOARD_REPO)
}

set output_dir [file normalize [file join [pwd] build vivado_2025_2]]
set project_name "rfsoc_adc_hardware_2025_2"
set export_xsa ""
set export_hw_emu_xsa ""
set run_build 0
set jobs 8

for {set i 0} {$i < $::argc} {incr i} {
  set option [lindex $::argv $i]
  switch -- $option {
    "--board_repo" {
      incr i
      set board_repo_arg [::rfsoc_adc_2025_2::require_arg $option $i]
    }
    "--output_dir" {
      incr i
      set output_dir [file normalize [::rfsoc_adc_2025_2::require_arg $option $i]]
    }
    "--project_name" {
      incr i
      set project_name [::rfsoc_adc_2025_2::require_arg $option $i]
    }
    "--export_xsa" {
      incr i
      set export_xsa [file normalize [::rfsoc_adc_2025_2::require_arg $option $i]]
    }
    "--export_hw_emu_xsa" {
      incr i
      set export_hw_emu_xsa [file normalize [::rfsoc_adc_2025_2::require_arg $option $i]]
    }
    "--build" {
      set run_build 1
    }
    "--jobs" {
      incr i
      set jobs [::rfsoc_adc_2025_2::require_arg $option $i]
      if {![string is integer -strict $jobs] || $jobs < 1} {
        ::rfsoc_adc_2025_2::fail "--jobs must be a positive integer"
      }
    }
    "--help" {
      ::rfsoc_adc_2025_2::usage
      return
    }
    default {
      ::rfsoc_adc_2025_2::usage
      ::rfsoc_adc_2025_2::fail "unknown option '$option'"
    }
  }
}

set running_version [version -short]
if {![string match "${::rfsoc_adc_2025_2::expected_version}*" $running_version]} {
  ::rfsoc_adc_2025_2::fail \
    "requires Vivado 2025.2, but the active tool reports '$running_version'"
}
puts "INFO: Running with Vivado $running_version"

if {$board_repo_arg eq ""} {
  set configured_repos {}
  catch {set configured_repos [get_param board.repoPaths]}
  foreach configured_repo $configured_repos {
    if {![catch {
      set board_repo_arg [::rfsoc_adc_2025_2::resolve_board_repo $configured_repo]
    }]} {
      break
    }
    set board_repo_arg ""
  }
}

if {$board_repo_arg eq ""} {
  ::rfsoc_adc_2025_2::fail \
    "set --board_repo or RFSOC4X2_BOARD_REPO to the RealDigital BSP checkout"
}

set ::rfsoc_adc_2025_2::board_repo_dir \
  [::rfsoc_adc_2025_2::resolve_board_repo $board_repo_arg]
set_param board.repoPaths [list $::rfsoc_adc_2025_2::board_repo_dir]

set expected_board_part "realdigital.org:rfsoc4x2:part0:1.0"
if {[llength [get_board_parts -quiet $expected_board_part]] != 1} {
  ::rfsoc_adc_2025_2::fail \
    "Vivado did not discover board part '$expected_board_part' in '$::rfsoc_adc_2025_2::board_repo_dir'"
}
puts "INFO: Using board files from $::rfsoc_adc_2025_2::board_repo_dir"

set legacy_tcl [file join $::rfsoc_adc_2025_2::script_dir rfsoc_adc_hardware_2023_2_1.tcl]
if {![file isfile $legacy_tcl]} {
  ::rfsoc_adc_2025_2::fail "cannot find the source design Tcl '$legacy_tcl'"
}

set legacy_channel [open $legacy_tcl r]
set legacy_text [read $legacy_channel]
close $legacy_channel

set old_board_repo_line \
  {set_property -name "board_part_repo_paths" -value "[file normalize "$origin_dir/../RFSoC4x2-BSP"]" -objects $obj}
set new_board_repo_line \
  {set_property -name "board_part_repo_paths" -value $::rfsoc_adc_2025_2::board_repo_dir -objects $obj}

if {[string first $old_board_repo_line $legacy_text] < 0} {
  ::rfsoc_adc_2025_2::fail \
    "the 2023.2.1 source changed: board repository adaptation point was not found"
}
foreach legacy_flow {
  {Vivado Synthesis 2023}
  {Vivado Implementation 2023}
} {
  if {[string first $legacy_flow $legacy_text] < 0} {
    ::rfsoc_adc_2025_2::fail \
      "the 2023.2.1 source changed: expected run flow '$legacy_flow' was not found"
  }
}

set migrated_text [string map [list \
  $old_board_repo_line $new_board_repo_line \
  {Vivado Synthesis 2023} {Vivado Synthesis 2025} \
  {Vivado Implementation 2023} {Vivado Implementation 2025} \
] $legacy_text]

# Project Tcl exported by Vivado 2023.2.1 includes session message filters and
# file metadata that should not be replayed in 2025.2. In particular, LIBRARY
# is now read-only on the generated block-design file. These lines do not
# describe design behavior, interfaces, clocks, or constraints.
set incompatible_generated_lines [list \
  {set_msg_config  -severity {STATUS}  -suppress  -ruleid {1}  -source 2} \
  {set_msg_config  -severity {INFO}  -suppress  -ruleid {2}  -source 2} \
  {set_msg_config  -severity {WARNING}  -suppress  -ruleid {3}  -source 2} \
  {set_msg_config  -severity {CRITICAL WARNING}  -suppress  -ruleid {4}  -source 2} \
  {set_property LIBRARY "xil_defaultlib" [get_files system.bd ]} \
]
foreach generated_line $incompatible_generated_lines {
  if {[string first $generated_line $migrated_text] < 0} {
    ::rfsoc_adc_2025_2::fail \
      "the 2023.2.1 source changed: compatibility line was not found: $generated_line"
  }
  set replacement \
    "# Vivado 2025.2 migration: omitted generated session/file metadata"
  set migrated_text [string map [list $generated_line $replacement] $migrated_text]
}

# The legacy ILA probes pps_trigger_axis_0/m_axis_tready directly. In the
# extensible-platform flow, Vitis owns and reconstructs the exported AXIS
# connection during linking. The native TREADY tap is consequently detached
# from the bundled interface and leaves an unconnected ILA channel, which
# Vivado 2025.2 rejects with VPL 16-213 during implementation. Keep the three
# adapter status probes and reset, but remove the AXIS-ready probe.
set legacy_probe4_width "    CONFIG.C_PROBE4_WIDTH {1} \\"
set legacy_ready_probe {
  connect_bd_net -net pps_trigger_axis_ready [get_bd_pins pps_trigger_axis_0/m_axis_tready] [get_bd_pins ila_pps_trigger/probe3]}

foreach adaptation [list \
  [list \
    {PPS ILA probe count} \
    {CONFIG.C_NUM_OF_PROBES {5}} \
    {CONFIG.C_NUM_OF_PROBES {4}}] \
  [list \
    {PPS ILA probe4 width} \
    $legacy_probe4_width \
    ""] \
  [list \
    {PPS AXIS-ready ILA connection} \
    $legacy_ready_probe \
    ""] \
  [list \
    {PPS ILA reset probe index} \
    {[get_bd_pins ila_pps_trigger/probe4]} \
    {[get_bd_pins ila_pps_trigger/probe3]}] \
] {
  lassign $adaptation description legacy_fragment migrated_fragment
  if {[string first $legacy_fragment $migrated_text] < 0} {
    ::rfsoc_adc_2025_2::fail \
      "the 2023.2.1 source changed: $description adaptation point was not found"
  }
  set migrated_text \
    [string map [list $legacy_fragment $migrated_fragment] $migrated_text]
}

foreach stale_flow {
  {Vivado Synthesis 2023}
  {Vivado Implementation 2023}
} {
  if {[string first $stale_flow $migrated_text] >= 0} {
    ::rfsoc_adc_2025_2::fail \
      "failed to replace stale run flow '$stale_flow'"
  }
}

file mkdir $output_dir
set project_dir [file join $output_dir $project_name]
if {[file exists $project_dir]} {
  ::rfsoc_adc_2025_2::fail \
    "project directory '$project_dir' already exists; use a fresh output directory or project name"
}

set migrated_tcl [file join $output_dir "${project_name}_migrated.tcl"]
set migrated_channel [open $migrated_tcl w]
puts -nonewline $migrated_channel $migrated_text
close $migrated_channel
puts "INFO: Wrote the adapted project source to $migrated_tcl"

set start_dir [pwd]
set saved_argv $::argv
set saved_argc $::argc
set had_origin_dir_loc [info exists ::origin_dir_loc]
if {$had_origin_dir_loc} {
  set saved_origin_dir_loc $::origin_dir_loc
}
set had_user_project_name [info exists ::user_project_name]
if {$had_user_project_name} {
  set saved_user_project_name $::user_project_name
}

set ::origin_dir_loc $::rfsoc_adc_2025_2::script_dir
set ::user_project_name $project_name
set ::argv {}
set ::argc 0
cd $output_dir

set source_rc [catch {source $migrated_tcl} source_message source_options]

cd $start_dir
set ::argv $saved_argv
set ::argc $saved_argc
if {$had_origin_dir_loc} {
  set ::origin_dir_loc $saved_origin_dir_loc
} else {
  unset ::origin_dir_loc
}
if {$had_user_project_name} {
  set ::user_project_name $saved_user_project_name
} else {
  unset ::user_project_name
}

if {$source_rc != 0} {
  return -options $source_options $source_message
}

set system_bd [get_files -quiet *system.bd]
if {[llength $system_bd] != 1} {
  ::rfsoc_adc_2025_2::fail "expected one generated system.bd, found [llength $system_bd]"
}

open_bd_design -quiet [lindex $system_bd 0]
validate_bd_design
save_bd_design
generate_target all [lindex $system_bd 0]
update_compile_order -fileset sources_1

set ip_status_report [file join $output_dir "${project_name}_ip_status.rpt"]
if {[catch {report_ip_status -file $ip_status_report -force} ip_status_message]} {
  puts "WARNING: Could not write IP status report: $ip_status_message"
} else {
  puts "INFO: Wrote IP status report to $ip_status_report"
}

if {[catch {
  set_property platform.platform_state "pre_synth" [current_project]
} platform_state_message]} {
  if {$export_xsa ne "" || $export_hw_emu_xsa ne ""} {
    ::rfsoc_adc_2025_2::fail \
      "cannot mark the project as a pre-synthesis extensible platform: $platform_state_message"
  }
  puts "WARNING: Could not set platform.platform_state to pre_synth: $platform_state_message"
} elseif {[get_property platform.platform_state [current_project]] ne "pre_synth"} {
  ::rfsoc_adc_2025_2::fail \
    "Vivado did not retain platform.platform_state=pre_synth"
}

if {$run_build} {
  ::rfsoc_adc_2025_2::run_to_completion synth_1 $jobs
  ::rfsoc_adc_2025_2::run_to_completion \
    impl_1 $jobs -to_step write_bitstream
}

if {$export_xsa ne ""} {
  file mkdir [file dirname $export_xsa]
  write_hw_platform -hw -force -file $export_xsa
  puts "INFO: Wrote pre-synthesis extensible hardware XSA to $export_xsa"
}

if {$export_hw_emu_xsa ne ""} {
  file mkdir [file dirname $export_hw_emu_xsa]
  write_hw_platform -hw_emu -force -file $export_hw_emu_xsa
  puts "INFO: Wrote hardware-emulation XSA to $export_hw_emu_xsa"
}

puts "INFO: Vivado 2025.2 migration project created at $project_dir"
