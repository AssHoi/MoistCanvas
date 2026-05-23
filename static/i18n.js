(function(){
    const KEY = 'studio_lang';
    const DEFAULT_LANG = 'zh';
    const dict = {
        zh: {
            'api.addProvider': '新增平台',
            'api.baseUrl': '请求地址',
            'api.basicHint': '平台显示名、唯一 ID 和请求地址',
            'api.basicInfo': '基本信息',
            'api.chatHint': 'GPT 对话和 LLM 节点使用。',
            'api.chatModels': '聊天模型',
            'api.confirmClearKey': '确认清除当前 Key？',
            'api.delete': '删除',
            'api.duplicateId': '平台 ID 不能重复',
            'api.editorSub': '配置基础信息、API Key 和可用模型',
            'api.enterKey': '输入 API Key',
            'api.enterKeyAlert': '请输入 Key',
            'api.fetchingModels': '拉取中...',
            'api.fetchModels': '拉取模型',
            'api.imageHint': '在线生图和无限画布 API 生成使用。',
            'api.imageModels': '生图模型',
            'api.keepCurrentKey': '保持当前 Key',
            'api.keepOne': '至少保留一个 API 平台',
            'api.keyHint': '写入后端 env，页面不显示完整内容。可单独保存或清除当前 Key。',
            'api.keySaved': '当前 Key 已保存：',
            'api.loadFailed': 'API 平台加载失败',
            'api.loading': '加载中...',
            'api.model': '模型',
            'api.msChinaEndpoint': '国内默认请求地址：',
            'api.msCnModels': '中文模型库：',
            'api.msEnModels': '英文模型库：',
            'api.msGlobalEndpoint': '国外使用请求地址：',
            'api.msModelExample': '模型名称示意：',
            'api.msTokenCn': '获取 Token · 国内：',
            'api.msTokenGlobal': '获取 Token · 国外：',
            'api.newProvider': '新 API 平台',
            'api.noKey': '还没有保存 Key。',
            'api.noModels': '暂无模型',
            'api.platformIdShown': '平台 ID',
            'api.platformName': '平台名称',
            'api.provider': '平台',
            'api.providersTitle': '平台列表',
            'api.save': '保存',
            'api.saved': '已保存，模型列表会立即同步到画布。',
            'api.saveFailed': '保存失败',
            'api.saving': '保存中...',
            'api.subtitle': '管理平台地址、模型列表和 Key。Key 写入后端 env，页面不会回显完整内容。',
            'api.testingUrl': '验证中...',
            'api.testUrl': '验证地址',
            'api.title': 'API 设置',
            'api.urlInvalid': '验证未通过',
            'api.urlTestDisclaimer': '注：本验证调用 OpenAI 标准格式的 <code>/v1/models</code> 端点。如果该平台不是 OpenAI 兼容接口，验证失败<strong>不一定</strong>代表地址不可用，请自行确认。',
            'api.urlValid': '地址可用',
            'api.videoHint': '无限画布视频生成节点使用。',
            'api.videoModels': '视频模型',
        },
        en: {
            'api.addProvider': 'Add Provider',
            'api.baseUrl': 'Base URL',
            'api.basicHint': 'Display name, unique ID, and base URL',
            'api.basicInfo': 'Basic Info',
            'api.chatHint': 'Used by GPT Chat and LLM nodes.',
            'api.chatModels': 'Chat Models',
            'api.confirmClearKey': 'Clear the current key?',
            'api.delete': 'Delete',
            'api.duplicateId': 'Provider IDs must be unique',
            'api.editorSub': 'Configure basics, API key, and available models',
            'api.enterKey': 'Enter API key',
            'api.enterKeyAlert': 'Please enter a key',
            'api.fetchingModels': 'Fetching...',
            'api.fetchModels': 'Fetch Models',
            'api.imageHint': 'Used by Online Image and Canvas API generation.',
            'api.imageModels': 'Image Models',
            'api.keepCurrentKey': 'Keep current key',
            'api.keepOne': 'Keep at least one API provider',
            'api.keyHint': 'Stored in backend env, never fully shown. Save or clear the key independently.',
            'api.keySaved': 'Key saved: ',
            'api.loadFailed': 'Failed to load API providers',
            'api.loading': 'Loading...',
            'api.model': 'Model',
            'api.msChinaEndpoint': 'China endpoint: ',
            'api.msCnModels': 'CN models: ',
            'api.msEnModels': 'EN models: ',
            'api.msGlobalEndpoint': 'Global endpoint: ',
            'api.msModelExample': 'Model ID example: ',
            'api.msTokenCn': 'Token (CN): ',
            'api.msTokenGlobal': 'Token (Global): ',
            'api.newProvider': 'New API Provider',
            'api.noKey': 'No key saved yet.',
            'api.noModels': 'No models',
            'api.platformIdShown': 'Platform ID',
            'api.platformName': 'Platform Name',
            'api.provider': 'Provider',
            'api.providersTitle': 'Platforms',
            'api.save': 'Save',
            'api.saved': 'Saved. Model lists sync to Canvas immediately.',
            'api.saveFailed': 'Save failed',
            'api.saving': 'Saving...',
            'api.subtitle': 'Manage provider URLs, model lists, and keys. Keys are saved to the backend env and are never fully shown here.',
            'api.testingUrl': 'Testing...',
            'api.testUrl': 'Test URL',
            'api.title': 'API Settings',
            'api.urlInvalid': 'Test did not pass',
            'api.urlTestDisclaimer': 'Note: this test calls the standard OpenAI <code>/v1/models</code> endpoint. If the platform is not OpenAI-compatible, a failure does <strong>not necessarily</strong> mean the URL is unusable — please verify manually.',
            'api.urlValid': 'URL works',
            'api.videoHint': 'Used by Infinite Canvas video generation nodes.',
            'api.videoModels': 'Video Models',
        }
    };
    function lang(){
        return localStorage.getItem(KEY) || DEFAULT_LANG;
    }
    function t(key){
        const current = lang();
        return dict[current]?.[key] || dict[DEFAULT_LANG]?.[key] || key;
    }
    function apply(root=document){
        root.querySelectorAll('[data-i18n]').forEach(el => {
            el.textContent = t(el.dataset.i18n);
        });
        root.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.setAttribute('placeholder', t(el.dataset.i18nPlaceholder));
        });
        root.querySelectorAll('[data-i18n-title]').forEach(el => {
            el.setAttribute('title', t(el.dataset.i18nTitle));
        });
        root.documentElement?.setAttribute('lang', lang() === 'en' ? 'en' : 'zh-CN');
        window.dispatchEvent(new CustomEvent('studio-lang-change', { detail:{ lang:lang() } }));
    }
    function set(next){
        localStorage.setItem(KEY, next === 'en' ? 'en' : 'zh');
        apply();
    }
    function toggle(){
        set(lang() === 'en' ? 'zh' : 'en');
    }
    window.StudioI18n = { t, apply, set, toggle, lang };
    document.addEventListener('DOMContentLoaded', () => apply());
})();
