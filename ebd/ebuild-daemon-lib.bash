# ebuild daemon lib code
# Copyright 2005-2012 Brian Harring <ferringb@gmail.com>
# License BSD/GPL2

PKGCORE_EBD_PID=${BASHPID}
# Use ebd_read/ebd_write for talking to the running pkgcore instance instead of
# echo'ing to the fd yourself. This allows us to move the open fd's w/out
# issues down the line.
__ebd_read_line_nonfatal() {
	read -u ${PKGCORE_EBD_READ_FD} $1
}

__ebd_read_line() {
	__ebd_read_line_nonfatal "$@"
	local ret=$?
	[[ ${ret} -ne 0 ]] && \
		die "coms error in ${PKGCORE_EBD_PID}, read_line $@ failed w/ ${ret}: backing out of daemon."
}

# read -N usage requires bash-4.1 or so (EAPI 6 requires >= 4.2)
__ebd_read_size() {
	read -u ${PKGCORE_EBD_READ_FD} -r -N $1 $2
	local ret=$?
	[[ ${ret} -ne 0 ]] && \
		die "coms error in ${PKGCORE_EBD_PID}, read_size $@ failed w/ ${ret}: backing out of daemon."
}

__ebd_read_cat_size() {
	dd bs=$1 count=1 <&${PKGCORE_EBD_READ_FD}
}

__ebd_write_line() {
	echo "$*" >&${PKGCORE_EBD_WRITE_FD}
	local ret=$?
	[[ ${ret} -ne 0 ]] && \
		die "coms error, write failed w/ ${ret}: backing out of daemon."
}

__ebd_write_raw() {
	echo -n "$*" >&${PKGCORE_EBD_WRITE_FD} || die "coms error, __ebd_write_raw failed;  Backing out."
}

__ipc_exit() {
	[[ $1 == 0 ]] && exit 0
	# exit in a helper compatible way when running IPC command from a helper
	[[ -n ${HELPER_ERROR_PREFIX} ]] && __helper_exit "$@"

	local ret=$1 msg=$2
	local error_msg="${IPC_CMD}: exitcode ${ret}"
	[[ -n ${msg} ]] && error_msg+=": ${msg}"

	if ${PKGCORE_NONFATAL}; then
		eerror "${error_msg}"
		exit ${ret}
	fi

	die "${error_msg}"
}

# run an ebuild command on the python side and return its status
__ebd_ipc_cmd() {
	local IPC_CMD=$1 opts=$2 ret_str
	local -a ret
	shift 2

	__ebd_write_line ${IPC_CMD}
	__ebd_write_line ${PKGCORE_NONFATAL:-false}
	__ebd_write_line ${PWD}
	__ebd_write_line ${opts}
	# Send arg list as a single string using a null char delimiter terminated by a newline.
	# Note that this requires printf as echo doesn't appear to respect IFS=$'\0'.
	printf "%s\0" "$@" >&${PKGCORE_EBD_WRITE_FD}
	__ebd_write_line

	# Split return status into array of return code and optional error message.
	# This uses a bell char as a delimiter since the null char can't be
	# assigned to variables.
	__ebd_read_line ret_str
	IFS=$'\x07' read -ra ret <<< "${ret_str}"
	__ipc_exit "${ret[@]}"
}

# ask the python side to display sandbox complaints
__request_sandbox_summary() {
	local line
	__ebd_write_line "__request_sandbox_summary ${SANDBOX_LOG}"
	__ebd_read_line line
	while [[ ${line} != "end_sandbox_summary" ]]; do
		echo "${line}"
		__ebd_read_line line
	done
}

__internal_inherit() {
	local line
	if [[ $# -ne 1 ]]; then
		die "internal_inherit accepts one arg, requested eclass location.  $* is a bit much"
	fi
	if [[ -n ${PKGCORE_PRELOADED_ECLASSES[$1]} ]]; then
		__qa_invoke "${PKGCORE_PRELOADED_ECLASSES[$1]}"
		return
	fi
	__ebd_write_line "request_inherit $1"
	__ebd_read_line line
	if [[ ${line} == "path" ]]; then
		__ebd_read_line line
		__qa_invoke source "${line}" >&2 || die "failed sources inherit: ${line}"
	elif [[ ${line} == "transfer" ]]; then
		__ebd_read_line line
		__qa_invoke eval "${line}" || die "failed evaluating eclass $1 on an inherit transfer"
	elif [[ ${line} == "failed" ]]; then
		die "inherit for $1 failed"
	else
		die "unknown inherit command from pythonic side, '${line}' for eclass $1"
	fi
}

__source_bashrcs() {
	${PKGCORE_SUPPRESS_BASHRCS:-false} && return
	local line
	__ebd_write_line "request_bashrcs"
	__ebd_read_line line
	while [[ ${line} != "end_request" ]]; do
		if [[ ${line} == "path" ]]; then
			__ebd_read_line line
			source "${line}" >&2
		elif [[ ${line} == "transfer" ]]; then
			__ebd_read_line line
			eval "${line}" || die "failed evaluating profile bashrc: ${line}"
		else
			__ebd_write_line "failed"
			die "unknown profile bashrc transfer mode from pythonic side, '${line}'"
		fi
		__ebd_write_line "next"
		__ebd_read_line line
	done
}

:
