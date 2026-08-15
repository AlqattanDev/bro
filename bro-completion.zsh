# Tab completion for bro. Always loaded (not gated on being inside a bro
# session) so `bro <tab>` works from any terminal.
#   source $HOME/.bro/bro-completion.zsh

if (( $+functions[compdef] )); then
  _bro() {
    local -a cmds
    cmds=(
      'quiet:no voice — answers on F1'
      'call:voice, keep going'
      'ping:one voice reply, then silent'
      'status:show current talk mode'
      'ask:send a note, safe even if it starts with a subcommand word'
      'snapshot:save your pane for bro'
      'read:print latest snapshot'
      'stop:end session'
      'backend:show/set backend'
      'help:show usage'
    )
    if (( CURRENT == 2 )); then
      _describe -t commands 'bro' cmds
    elif (( CURRENT == 3 )) && [[ ${words[2]} == backend ]]; then
      local -a backends
      backends=('grok' 'claude' 'codex')
      _describe -t backends 'backend' backends
    fi
  }
  compdef _bro bro
fi
