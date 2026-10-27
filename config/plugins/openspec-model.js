// sandbox-code: pin the model of the `openspec-plan` agent.
//
// `opencode-plugin-openspec` adds the `openspec-plan` agent from its `config`
// hook, but it replaces the whole agent entry and never sets a `model`, so a
// plain `agent.openspec-plan.model` in opencode.jsonc is dropped. Plugins
// declared in the config load before the global plugin directory, so this
// plugin runs afterwards and re-applies the model.
const OPENSPEC_PLAN_MODEL = "openrouter/deepseek/deepseek-v4-pro"

export const OpenSpecModelPlugin = async () => ({
  config: async (config) => {
    config.agent = config.agent || {}
    const agent = config.agent["openspec-plan"]
    if (agent) {
      agent.model = OPENSPEC_PLAN_MODEL
    }
  },
})
