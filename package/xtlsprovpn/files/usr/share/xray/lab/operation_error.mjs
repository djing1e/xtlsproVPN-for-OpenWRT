"use strict";
// Whitelisted messages only: logs can contain subscription URLs and credentials.
export function operation_error(text, fallback) {
    const memory=index(text || '', 'Not enough RAM for isolated candidate testing')>=0;
    if(memory) {
        let n=match(text,/required_kb=([0-9]+); available_kb=([0-9]+)/);
        return n ? sprintf('Недостаточно RAM для проверки подписки: требуется %d МиБ, доступно %d МиБ. Рабочая конфигурация сохранена.',
            int((int(n[1])+1023)/1024),int(int(n[2])/1024)) :
            'Недостаточно RAM для отдельной проверки подписки. Рабочая конфигурация сохранена.';
    }
    const download=match(text || '',/Subscription download failed: curl=([0-9]+), HTTP=([0-9]+)/);
    if(download)return 'Не удалось загрузить подписку: curl='+download[1]+', HTTP='+download[2]+'.';
    if(index(text || '', 'allowInsecure')>=0)return 'Конфигурация отклонена: устаревший TLS allowInsecure. Рабочая конфигурация сохранена.';
    if(index(text || '', 'Candidate HTTPS failed')>=0)return 'Узел подписки не прошёл HTTPS-проверку. Рабочая конфигурация сохранена.';
    if(index(text || '', 'Candidate DNS failed')>=0)return 'Кандидат не прошёл DNS-проверку. Рабочая конфигурация сохранена.';
    if(index(text || '', 'Candidate process failed')>=0)return 'Проверяющий процесс не запустился или завершился. Рабочая конфигурация сохранена.';
    if(index(text || '', 'Previous configuration restored;')>=0)return 'Новая конфигурация не прошла проверку; предыдущая восстановлена.';
    return fallback;
};
